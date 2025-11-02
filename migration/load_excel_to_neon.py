#!/usr/bin/env python3
"""
Typer-based CLI for migrating Excel extracts into Neon Postgres.

Commands:
    init-db         – Create required schemas and helper tables.
    infer           – Inspect an Excel sheet and infer column metadata.
    create-staging  – Build or evolve the staging table structure.
    load-staging    – Load data from Excel into the staging table (full or incremental).
    promote-core    – Run SQL to promote staging rows into the core schema.
    build-analytics – Build analytics-layer views/materializations.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
import typer
import yaml
from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import postgresql as pg_dialect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql.compiler import IdentifierPreparer

APP_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = APP_DIR / "config.yaml"
ENV_PATH = APP_DIR / ".env"

app = typer.Typer(help="Excel → Neon migration utilities")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

load_dotenv(dotenv_path=ENV_PATH, override=False)

PREPARER = IdentifierPreparer(pg_dialect.dialect())


class ConfigError(RuntimeError):
    """Raised when configuration is missing or invalid."""


def sanitize_column_name(name: str) -> str:
    """Standardise column names to Postgres-safe identifiers."""
    import re
    import unicodedata

    if name is None:
        name = ""
    cleaned = unicodedata.normalize("NFKD", str(name)).strip().lower()
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = re.sub(r"[^0-9a-z_]+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = cleaned.strip("_")
    if not cleaned:
        cleaned = "column"
    return cleaned[:63]


def quote_ident(identifier: str) -> str:
    return PREPARER.quote(identifier)


def quote_table(table_name: str) -> str:
    parts = table_name.split(".")
    return ".".join(quote_ident(part) for part in parts)


def quote_column_list(columns: Iterable[str]) -> str:
    return ", ".join(quote_ident(col) for col in columns)


def split_table_identifier(table_identifier: str) -> Tuple[Optional[str], str]:
    if "." in table_identifier:
        schema, name = table_identifier.split(".", 1)
        return schema, name
    return None, table_identifier


def load_engine() -> Engine:
    conn_str = os.getenv("NEON_DATABASE_URL")
    if not conn_str:
        raise typer.BadParameter(
            "NEON_DATABASE_URL is not set. Populate migration/.env or export it."
        )
    try:
        engine = create_engine(conn_str, future=True)
        return engine
    except SQLAlchemyError as exc:
        raise RuntimeError(f"Failed to create database engine: {exc}") from exc


def ensure_schema(engine: Engine, schema: str) -> None:
    if not schema:
        return
    stmt = text(f"CREATE SCHEMA IF NOT EXISTS {quote_ident(schema)}")
    with engine.begin() as conn:
        conn.execute(stmt)


def ensure_column_name_map(engine: Engine) -> None:
    ensure_schema(engine, "stg")
    ddl = """
    CREATE TABLE IF NOT EXISTS stg._column_name_map (
        table_name text NOT NULL,
        source_column text NOT NULL,
        sanitized_column text NOT NULL,
        last_seen_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (table_name, sanitized_column)
    );
    """
    with engine.begin() as conn:
        conn.execute(text(ddl))


def upsert_column_name_map(
    engine: Engine, table_name: str, column_mapping: Dict[str, str]
) -> None:
    if not column_mapping:
        return
    ensure_column_name_map(engine)
    rows = [
        {
            "table_name": table_name,
            "sanitized_column": sanitized,
            "source_column": source,
        }
        for sanitized, source in column_mapping.items()
    ]
    sql = """
    INSERT INTO stg._column_name_map (table_name, source_column, sanitized_column, last_seen_at)
    VALUES (:table_name, :source_column, :sanitized_column, now())
    ON CONFLICT (table_name, sanitized_column)
    DO UPDATE SET source_column = EXCLUDED.source_column, last_seen_at = EXCLUDED.last_seen_at;
    """
    with engine.begin() as conn:
        conn.execute(text(sql), rows)


def parse_column_list(option: Optional[str]) -> List[str]:
    if not option:
        return []
    columns = []
    for item in option.split(","):
        sanitized = sanitize_column_name(item)
        if sanitized:
            columns.append(sanitized)
    return columns


def sanitize_dataframe(
    df: pd.DataFrame,
) -> Tuple[pd.DataFrame, Dict[str, str]]:
    rename_map: Dict[str, str] = {}
    sanitized_to_source: Dict[str, str] = {}
    used: Dict[str, int] = {}
    for original in df.columns:
        base = sanitize_column_name(original)
        candidate = base
        while candidate in sanitized_to_source:
            counter = used.get(base, 1) + 1
            used[base] = counter
            candidate = f"{base}_{counter}"
        sanitized_to_source[candidate] = original
        rename_map[original] = candidate
        used.setdefault(base, 1)
    sanitized_df = df.rename(columns=rename_map)
    return sanitized_df, sanitized_to_source


def map_dtype_to_sql(series: pd.Series) -> str:
    dtype = series.dtype
    if pd.api.types.is_datetime64_any_dtype(
        dtype
    ) or pd.api.types.is_datetime64tz_dtype(dtype):
        return "timestamptz"
    if pd.api.types.is_bool_dtype(dtype):
        return "boolean"
    if pd.api.types.is_integer_dtype(dtype):
        return "bigint"
    if pd.api.types.is_float_dtype(dtype):
        return "numeric(18,4)"
    # Attempt to detect date objects stored as object dtype
    sample = series.dropna().head(1)
    if not sample.empty and getattr(sample.iloc[0], "__class__", None).__name__ in {
        "date",
    }:
        return "date"
    return "text"


def infer_type_map(
    df: pd.DataFrame, existing: Optional[Dict[str, Dict[str, str]]] = None
) -> Dict[str, str]:
    inferred: Dict[str, str] = {}
    for column in df.columns:
        override = (
            existing.get(column, {}).get("type")
            if existing and column in existing
            else None
        )
        inferred[column] = override or map_dtype_to_sql(df[column])
    return inferred


def dataframe_to_csv_chunks(
    df: pd.DataFrame, chunk_size: int
) -> Iterable[Tuple[io.StringIO, bool]]:
    total_rows = len(df.index)
    if total_rows == 0:
        buffer = io.StringIO()
        df.head(0).to_csv(buffer, index=False, header=True)
        buffer.seek(0)
        yield buffer, True
        return
    include_header = True
    for start in range(0, total_rows, chunk_size):
        chunk = df.iloc[start : start + chunk_size]
        buf = io.StringIO()
        chunk.to_csv(buf, index=False, header=include_header)
        buf.seek(0)
        yield buf, include_header
        include_header = False


def copy_dataframe(
    engine: Engine, df: pd.DataFrame, table_name: str, chunk_size: int
) -> None:
    quoted_table = quote_table(table_name)
    columns = df.columns.tolist()
    if not columns:
        return
    sql_header = f"COPY {quoted_table} ({quote_column_list(columns)}) FROM STDIN WITH "
    raw_conn = engine.raw_connection()
    try:
        with raw_conn.cursor() as cur:  # type: ignore[attr-defined]
            for buffer, first_chunk in dataframe_to_csv_chunks(df, chunk_size):
                options = "CSV HEADER" if first_chunk else "CSV"
                cur.copy_expert(sql=sql_header + options, file=buffer)
        raw_conn.commit()
    finally:
        raw_conn.close()


def get_existing_columns(engine: Engine, table_name: str) -> Dict[str, Dict[str, Any]]:
    schema, name = split_table_identifier(table_name)
    inspector = inspect(engine)
    try:
        columns = inspector.get_columns(name, schema=schema)
    except SQLAlchemyError:
        return {}
    return {col["name"]: col for col in columns}


def table_exists(engine: Engine, table_name: str) -> bool:
    schema, name = split_table_identifier(table_name)
    inspector = inspect(engine)
    return inspector.has_table(name, schema=schema)


def ensure_table_structure(
    engine: Engine,
    table_name: str,
    columns_cfg: Dict[str, Dict[str, Any]],
    primary_key: List[str],
) -> None:
    if not columns_cfg:
        raise ConfigError(
            f"No column definitions available for table '{table_name}'. Run infer first."
        )
    schema, _ = split_table_identifier(table_name)
    ensure_schema(engine, schema)
    exists = table_exists(engine, table_name)
    quoted_table = quote_table(table_name)
    if not exists:
        column_ddl = []
        for column, meta in columns_cfg.items():
            column_type = meta.get("type", "text")
            column_ddl.append(f"{quote_ident(column)} {column_type}")
        constraint = ""
        if primary_key:
            constraint = f", PRIMARY KEY ({quote_column_list(primary_key)})"
        ddl = f"CREATE TABLE IF NOT EXISTS {quoted_table} ({', '.join(column_ddl)}{constraint})"
        with engine.begin() as conn:
            conn.execute(text(ddl))
    else:
        existing_cols = get_existing_columns(engine, table_name)
        alter_statements = []
        for column, meta in columns_cfg.items():
            if column not in existing_cols:
                column_type = meta.get("type", "text")
                alter_statements.append(
                    f"ALTER TABLE {quoted_table} ADD COLUMN {quote_ident(column)} {column_type}"
                )
        if alter_statements:
            with engine.begin() as conn:
                for stmt in alter_statements:
                    conn.execute(text(stmt))

        if primary_key:
            inspector = inspect(engine)
            pk_info = inspector.get_pk_constraint(
                split_table_identifier(table_name)[1], schema=schema
            )
            pk_columns = pk_info.get("constrained_columns") if pk_info else []
            if not pk_columns:
                constraint_name = f"{split_table_identifier(table_name)[1]}_pk"
                alter = (
                    f"ALTER TABLE {quoted_table} ADD CONSTRAINT {quote_ident(constraint_name)} "
                    f"PRIMARY KEY ({quote_column_list(primary_key)})"
                )
                with engine.begin() as conn:
                    conn.execute(text(alter))


def ensure_unique_constraint(
    engine: Engine, table_name: str, key_columns: List[str], suffix: str
) -> None:
    if not key_columns:
        return
    schema, name = split_table_identifier(table_name)
    index_name = f"{name}_{'_'.join(key_columns)}_{suffix}"
    stmt = text(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {quote_ident(index_name)} "
        f"ON {quote_table(table_name)} ({quote_column_list(key_columns)})"
    )
    with engine.begin() as conn:
        conn.execute(stmt)


def apply_type_hints(
    df: pd.DataFrame, columns_cfg: Dict[str, Dict[str, Any]]
) -> pd.DataFrame:
    result = df.copy()
    for column, meta in columns_cfg.items():
        if column not in result.columns:
            continue
        target_type = (meta or {}).get("type", "").lower()
        if target_type in {"timestamptz", "timestamp", "timestamp with time zone"}:
            result[column] = pd.to_datetime(result[column], errors="coerce", utc=True)
        elif target_type == "date":
            result[column] = pd.to_datetime(result[column], errors="coerce").dt.date
        elif target_type.startswith("numeric") or target_type in {
            "decimal",
            "double precision",
        }:
            result[column] = pd.to_numeric(result[column], errors="coerce")
        elif target_type in {"bigint", "integer"}:
            numeric_series = pd.to_numeric(result[column], errors="coerce")
            result[column] = numeric_series.astype("Int64")
    return result


def validate_headers(
    df: pd.DataFrame,
    columns_cfg: Dict[str, Dict[str, Any]],
    allow_new_columns: bool,
) -> None:
    configured_columns = set(columns_cfg.keys())
    incoming_columns = set(df.columns)
    missing = configured_columns - incoming_columns
    new_columns = incoming_columns - configured_columns
    if missing:
        raise ConfigError(
            f"Incoming data is missing expected columns: {', '.join(sorted(missing))}"
        )
    if new_columns and not allow_new_columns:
        raise ConfigError(
            "New columns detected: "
            + ", ".join(sorted(new_columns))
            + ". Rerun infer with --allow-new-columns or update config."
        )


def add_new_columns_to_config(
    df: pd.DataFrame,
    columns_cfg: Dict[str, Dict[str, Any]],
    allow_new_columns: bool,
    source_mapping: Dict[str, str],
) -> Dict[str, Dict[str, Any]]:
    if not allow_new_columns:
        return columns_cfg
    updated = dict(columns_cfg)
    for column in df.columns:
        if column not in updated:
            inferred_type = map_dtype_to_sql(df[column])
            updated[column] = {
                "source": source_mapping.get(column, column),
                "type": inferred_type,
            }
            logger.info(
                "Allowing new column '%s' inferred as %s", column, inferred_type
            )
    return updated


def check_nulls(df: pd.DataFrame, key_columns: List[str]) -> None:
    if not key_columns:
        return
    for column in key_columns:
        if column not in df.columns:
            raise ConfigError(f"Key column '{column}' missing from incoming data.")
        if df[column].isna().any():
            raise ConfigError(f"Null values detected in key column '{column}'.")


def check_duplicates(df: pd.DataFrame, key_columns: List[str]) -> None:
    if not key_columns:
        return
    duplicated = df.duplicated(subset=key_columns, keep=False)
    if duplicated.any():
        sample = df.loc[duplicated, key_columns].head(5).to_dict(orient="records")
        raise ConfigError(
            "Duplicate key values detected in incoming batch "
            f"for keys {key_columns}: {json.dumps(sample, indent=2)}"
        )


def get_row_count(engine: Engine, table_name: str) -> int:
    stmt = text(f"SELECT COUNT(*) AS cnt FROM {quote_table(table_name)}")
    with engine.begin() as conn:
        result = conn.execute(stmt).scalar()
        return int(result or 0)


def check_row_count_sanity(
    previous_count: int,
    incoming_count: int,
    threshold: float,
    force: bool,
) -> None:
    if previous_count == 0 or incoming_count == 0:
        return
    minimum = int(previous_count * threshold)
    if incoming_count < minimum and not force:
        raise ConfigError(
            f"Incoming row count {incoming_count} is below {threshold:.0%} of previous load "
            f"({previous_count}). Use --force to override."
        )


def check_date_range(
    engine: Engine,
    table_name: str,
    incremental_key: Optional[str],
    incoming_df: pd.DataFrame,
    tolerance_days: int,
) -> None:
    if not incremental_key or incremental_key not in incoming_df.columns:
        return
    series = incoming_df[incremental_key].dropna()
    if series.empty:
        return
    incoming_max = series.max()
    stmt = text(
        f"SELECT MIN({quote_ident(incremental_key)}) AS min_key, "
        f"MAX({quote_ident(incremental_key)}) AS max_key "
        f"FROM {quote_table(table_name)}"
    )
    with engine.begin() as conn:
        row = conn.execute(stmt).mappings().one_or_none()
    if not row or row["max_key"] is None:
        return
    max_existing = row["max_key"]
    allowed_min = max_existing - timedelta(days=tolerance_days)
    if incoming_max < allowed_min:
        raise ConfigError(
            f"Incoming max {incoming_max} for {incremental_key} is older than "
            f"existing max {max_existing} (tolerance {tolerance_days} days)."
        )


def load_full_refresh(
    engine: Engine,
    df: pd.DataFrame,
    table_name: str,
    chunk_size: int,
) -> None:
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE {quote_table(table_name)}"))
    copy_dataframe(engine, df, table_name, chunk_size)


def load_incremental(
    engine: Engine,
    df: pd.DataFrame,
    table_name: str,
    conflict_columns: List[str],
    chunk_size: int,
) -> None:
    if not conflict_columns:
        raise ConfigError(
            "Incremental mode requires pk or upsert keys. Provide --pk/--upsert or configure in YAML."
        )
    quoted_table = quote_table(table_name)
    tmp_table = f"tmp_{uuid.uuid4().hex[:10]}"
    columns = df.columns.tolist()
    insert_columns = quote_column_list(columns)
    set_clauses = [
        f"{quote_ident(col)} = EXCLUDED.{quote_ident(col)}"
        for col in columns
        if col not in conflict_columns
    ]
    raw_conn = engine.raw_connection()
    try:
        with raw_conn.cursor() as cur:  # type: ignore[attr-defined]
            cur.execute(
                f"CREATE TEMP TABLE {quote_ident(tmp_table)} "
                f"(LIKE {quoted_table} INCLUDING DEFAULTS INCLUDING IDENTITY)"
            )
            for buffer, first_chunk in dataframe_to_csv_chunks(df, chunk_size):
                options = "CSV HEADER" if first_chunk else "CSV"
                copy_sql = f"COPY {quote_ident(tmp_table)} ({insert_columns}) FROM STDIN WITH {options}"
                cur.copy_expert(sql=copy_sql, file=buffer)
            conflict_clause = quote_column_list(conflict_columns)
            if set_clauses:
                update_clause = ", ".join(set_clauses)
                merge_sql = (
                    f"INSERT INTO {quoted_table} ({insert_columns}) "
                    f"SELECT {insert_columns} FROM {quote_ident(tmp_table)} "
                    f"ON CONFLICT ({conflict_clause}) DO UPDATE SET {update_clause}"
                )
            else:
                merge_sql = (
                    f"INSERT INTO {quoted_table} ({insert_columns}) "
                    f"SELECT {insert_columns} FROM {quote_ident(tmp_table)} "
                    f"ON CONFLICT ({conflict_clause}) DO NOTHING"
                )
            cur.execute(merge_sql)
        raw_conn.commit()
    finally:
        raw_conn.close()


@dataclass
class TableConfig:
    table_name: str
    file: Optional[str] = None
    sheet: Optional[str] = None
    pk: List[str] = field(default_factory=list)
    upsert_keys: List[str] = field(default_factory=list)
    incremental_key: Optional[str] = None
    allow_new_columns: bool = False
    chunk_size: int = 50000
    row_count_floor_pct: float = 0.5
    date_tolerance_days: int = 2
    source_timezone: Optional[str] = None
    columns: Dict[str, Dict[str, Any]] = field(default_factory=dict)


class ConfigStore:
    def __init__(self, path: Path):
        self.path = path
        self.data: Dict[str, Any] = {}
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        if self.path.exists():
            with self.path.open("r", encoding="utf-8") as fh:
                self.data = yaml.safe_load(fh) or {}
        self.data.setdefault("defaults", {})
        self.data.setdefault("tables", {})
        self._loaded = True

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(self.data, fh, sort_keys=False)

    def get_defaults(self) -> Dict[str, Any]:
        self.load()
        return self.data.get("defaults", {})

    def get_table(self, table_name: str) -> TableConfig:
        self.load()
        table_cfg = self.data.get("tables", {}).get(table_name)
        if not table_cfg:
            raise ConfigError(
                f"No configuration found for table '{table_name}'. "
                "Update migration/config.yaml or run infer with --save-overrides."
            )
        defaults = self.get_defaults()
        merged = dict(defaults)
        merged.update(table_cfg)
        return TableConfig(
            table_name=table_name,
            file=merged.get("file"),
            sheet=merged.get("sheet"),
            pk=list(merged.get("pk") or []),
            upsert_keys=list(merged.get("upsert_keys") or []),
            incremental_key=merged.get("incremental_key"),
            allow_new_columns=merged.get("allow_new_columns", False),
            chunk_size=int(
                merged.get("chunk_size") or defaults.get("chunk_size") or 50000
            ),
            row_count_floor_pct=float(
                merged.get("row_count_floor_pct")
                or defaults.get("row_count_floor_pct")
                or 0.5
            ),
            date_tolerance_days=int(
                merged.get("date_tolerance_days")
                or defaults.get("date_tolerance_days")
                or 2
            ),
            source_timezone=merged.get("source_timezone"),
            columns=dict(merged.get("columns") or {}),
        )

    def upsert_table(
        self,
        table_name: str,
        metadata: Dict[str, Any],
    ) -> None:
        self.load()
        tables = self.data.setdefault("tables", {})
        existing = tables.get(table_name, {})
        existing.update(metadata)
        tables[table_name] = existing
        self.save()


def resolve_config_path(config: Optional[Path]) -> Path:
    if config:
        return config
    return DEFAULT_CONFIG_PATH


def read_excel(file_path: Path, sheet: str) -> pd.DataFrame:
    try:
        df = pd.read_excel(file_path, sheet_name=sheet, engine="openpyxl")
        return df
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise RuntimeError(f"Failed to read Excel sheet '{sheet}': {exc}") from exc


@app.command("init-db")
def init_db(
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to migration config (optional)."
    ),
    quality_sql: Path = typer.Option(
        APP_DIR / "sql" / "init_quality_control.sql",
        "--quality-sql",
        help="Path to SQL file that seeds quality control tables.",
    ),
) -> None:
    """Create required schemas and helper tables."""
    engine = load_engine()
    for schema in ("stg", "core", "analytics"):
        ensure_schema(engine, schema)
    ensure_column_name_map(engine)
    run_sql_file(engine, quality_sql)
    config_store = ConfigStore(resolve_config_path(config))
    config_store.load()
    logger.info("Schemas ensured and config loaded from %s", config_store.path)


@app.command("infer")
def infer(
    file: Path = typer.Option(..., "--file", exists=True, help="Excel workbook path."),
    sheet: str = typer.Option(..., "--sheet", help="Worksheet name."),
    table: str = typer.Option(
        ..., "--table", help="Target staging table (e.g. stg.table)."
    ),
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Config file to read (defaults to migration/config.yaml).",
    ),
    save_overrides: Optional[Path] = typer.Option(
        None,
        "--save-overrides",
        help="If provided, write inferred metadata to this YAML config file.",
    ),
    sample_rows: int = typer.Option(
        5, "--sample-rows", help="Number of sample rows to print for inspection."
    ),
) -> None:
    """Infer column metadata from an Excel sheet."""
    df = read_excel(file, sheet)
    sanitized_df, mapping = sanitize_dataframe(df)
    target_path = save_overrides or resolve_config_path(config)
    config_store = ConfigStore(target_path)
    existing_columns = {}
    try:
        table_cfg = config_store.get_table(table)
        existing_columns = table_cfg.columns
    except ConfigError:
        existing_columns = {}

    inferred_types = infer_type_map(sanitized_df, existing_columns)
    preview = sanitized_df.head(sample_rows).to_dict(orient="records")
    logger.info("Inferred %d columns for %s", len(inferred_types), table)
    typer.echo(
        json.dumps(
            {"columns": inferred_types, "sample_rows": preview}, indent=2, default=str
        )
    )

    columns_cfg = {
        column: {
            "source": mapping[column],
            "type": inferred_types[column],
        }
        for column in inferred_types
    }
    payload = {
        "file": str(file),
        "sheet": sheet,
        "columns": columns_cfg,
    }
    config_store.upsert_table(table, payload)
    logger.info("Wrote inferred metadata to %s", config_store.path)


@app.command("create-staging")
def create_staging(
    table: str = typer.Option(..., "--table", help="Target staging table."),
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Config file to use (defaults to migration/config.yaml).",
    ),
) -> None:
    """Create or evolve the staging table using the saved configuration."""
    config_store = ConfigStore(resolve_config_path(config))
    table_cfg = config_store.get_table(table)
    engine = load_engine()
    ensure_table_structure(engine, table, table_cfg.columns, table_cfg.pk)
    ensure_unique_constraint(engine, table, table_cfg.upsert_keys or table_cfg.pk, "uk")
    upsert_column_name_map(
        engine, table, {k: v.get("source", k) for k, v in table_cfg.columns.items()}
    )
    logger.info("Staging table %s is ready.", table)


@app.command("load-staging")
def load_staging(
    file: Optional[Path] = typer.Option(
        None, "--file", help="Excel workbook path (defaults to config file entry)."
    ),
    sheet: Optional[str] = typer.Option(
        None, "--sheet", help="Worksheet name (defaults to config file entry)."
    ),
    table: str = typer.Option(..., "--table", help="Staging table to load."),
    mode: str = typer.Option(
        "full",
        "--mode",
        case_sensitive=False,
        help="full (truncate/replace) or incremental",
    ),
    incremental_key: Optional[str] = typer.Option(
        None, "--incremental-key", help="Override incremental key column."
    ),
    pk: Optional[str] = typer.Option(
        None, "--pk", help="Comma-separated primary key columns override."
    ),
    upsert_keys: Optional[str] = typer.Option(
        None, "--upsert-keys", help="Comma-separated upsert keys override."
    ),
    allow_new_columns: bool = typer.Option(
        False,
        "--allow-new-columns",
        help="Allow adding new columns detected in the data.",
    ),
    chunk_size: Optional[int] = typer.Option(
        None, "--chunk-size", help="Override chunk size for COPY batching."
    ),
    force: bool = typer.Option(False, "--force", help="Skip row-count sanity check."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview actions without modifying the database."
    ),
    validate_only: bool = typer.Option(
        False,
        "--validate-only",
        help="Run validations without writing to the database.",
    ),
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Config file path (defaults to migration/config.yaml).",
    ),
) -> None:
    """Load Excel data into the staging table."""
    config_store = ConfigStore(resolve_config_path(config))
    table_cfg = config_store.get_table(table)
    if file is None:
        if not table_cfg.file:
            raise ConfigError(
                "File path missing. Provide --file or set it in the config."
            )
        file = Path(table_cfg.file)
    if sheet is None:
        if not table_cfg.sheet:
            raise ConfigError(
                "Sheet name missing. Provide --sheet or set it in the config."
            )
        sheet = table_cfg.sheet
    if not file.exists():
        raise ConfigError(f"Excel file not found: {file}")

    df = read_excel(file, sheet)
    sanitized_df, mapping = sanitize_dataframe(df)

    columns_cfg = table_cfg.columns
    original_columns = dict(table_cfg.columns)
    columns_cfg = add_new_columns_to_config(
        sanitized_df,
        columns_cfg,
        allow_new_columns or table_cfg.allow_new_columns,
        mapping,
    )
    validate_headers(
        sanitized_df, columns_cfg, allow_new_columns or table_cfg.allow_new_columns
    )
    sanitized_df = apply_type_hints(sanitized_df, columns_cfg)

    key_columns = parse_column_list(pk) or table_cfg.pk
    upsert_columns = parse_column_list(upsert_keys) or table_cfg.upsert_keys
    incremental_column = (
        sanitize_column_name(incremental_key)
        if incremental_key
        else table_cfg.incremental_key
    )

    check_nulls(sanitized_df, key_columns)
    check_duplicates(sanitized_df, key_columns or upsert_columns)

    engine = load_engine()
    ensure_table_structure(engine, table, columns_cfg, key_columns)
    ensure_unique_constraint(engine, table, upsert_columns or key_columns, "uk")
    upsert_column_name_map(
        engine,
        table,
        {k: v.get("source", mapping.get(k, k)) for k, v in columns_cfg.items()},
    )

    update_payload: Dict[str, Any] = {}
    if columns_cfg != original_columns:
        update_payload["columns"] = columns_cfg
    if str(file) != (table_cfg.file or ""):
        update_payload["file"] = str(file)
    if sheet != (table_cfg.sheet or ""):
        update_payload["sheet"] = sheet
    if update_payload:
        config_store.upsert_table(table, update_payload)

    existing_count = get_row_count(engine, table)
    incoming_count = len(sanitized_df.index)
    check_row_count_sanity(
        previous_count=existing_count,
        incoming_count=incoming_count,
        threshold=table_cfg.row_count_floor_pct,
        force=force,
    )
    check_date_range(
        engine=engine,
        table_name=table,
        incremental_key=incremental_column,
        incoming_df=sanitized_df,
        tolerance_days=table_cfg.date_tolerance_days,
    )

    chunk = chunk_size or table_cfg.chunk_size
    logger.info(
        "Prepared %s rows for %s (%s mode). Chunk size=%s.",
        incoming_count,
        table,
        mode,
        chunk,
    )

    if dry_run or validate_only:
        typer.echo(
            json.dumps(
                {
                    "table": table,
                    "mode": mode,
                    "row_count": incoming_count,
                    "columns": list(sanitized_df.columns),
                    "file": str(file),
                    "sheet": sheet,
                    "keys": key_columns or upsert_columns,
                },
                indent=2,
                default=str,
            )
        )
        return

    if mode.lower() == "full":
        load_full_refresh(engine, sanitized_df, table, chunk)
    elif mode.lower() == "incremental":
        load_incremental(
            engine, sanitized_df, table, upsert_columns or key_columns, chunk
        )
    else:
        raise typer.BadParameter("Mode must be 'full' or 'incremental'.")

    logger.info("Load complete: %s rows into %s.", incoming_count, table)

    period_detected = None
    month_key_detected = None
    if "accounting_period_name" in sanitized_df.columns:
        unique_periods = (
            sanitized_df["accounting_period_name"].dropna().unique().tolist()
        )
        if len(unique_periods) == 1:
            period_detected = str(unique_periods[0])
    if "accounting_period_start_date" in sanitized_df.columns:
        dates = pd.to_datetime(
            sanitized_df["accounting_period_start_date"].dropna(),
            utc=True,
            errors="coerce",
        )
        dates = dates.dropna()
        if not dates.empty:
            month_keys = dates.dt.to_period("M").astype(str).unique().tolist()
            if len(month_keys) == 1:
                month_key_detected = month_keys[0]

    metadata_payload = {
        "sheet": sheet,
        "mode": mode,
        "columns": list(sanitized_df.columns),
    }
    checksum_source = f"{file}:{incoming_count}:{mode}".encode("utf-8")
    checksum = hashlib.sha256(checksum_source).hexdigest()

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO stg.load_batch_log (
                    table_name,
                    source_file_name,
                    record_count,
                    load_mode,
                    period_detected,
                    month_key,
                    checksum,
                    metadata
                )
                VALUES (
                    :table_name,
                    :source_file_name,
                    :record_count,
                    :load_mode,
                    :period_detected,
                    :month_key,
                    :checksum,
                    CAST(:metadata AS jsonb)
                )
                """
            ),
            {
                "table_name": table,
                "source_file_name": str(file),
                "record_count": incoming_count,
                "load_mode": mode.lower(),
                "period_detected": period_detected,
                "month_key": month_key_detected,
                "checksum": checksum,
                "metadata": json.dumps(metadata_payload),
            },
        )

    logger.info(
        "Logged load batch for %s (%s rows, month=%s).",
        table,
        incoming_count,
        month_key_detected or "unknown",
    )


def split_sql_statements(contents: str) -> List[str]:
    statements: List[str] = []
    current: List[str] = []
    in_single_quote = False
    in_double_quote = False
    in_line_comment = False
    in_block_comment = False
    dollar_tag: str | None = None
    length = len(contents)
    index = 0

    def append_char(value: str) -> None:
        current.append(value)

    while index < length:
        ch = contents[index]
        next_two = contents[index : index + 2]

        if in_line_comment:
            append_char(ch)
            if ch == "\n":
                in_line_comment = False
            index += 1
            continue

        if in_block_comment:
            append_char(ch)
            if next_two == "*/":
                append_char("/")
                index += 2
                in_block_comment = False
            else:
                index += 1
            continue

        if dollar_tag is not None:
            if contents.startswith(dollar_tag, index):
                append_char(dollar_tag)
                index += len(dollar_tag)
                dollar_tag = None
            else:
                append_char(ch)
                index += 1
            continue

        if ch == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            append_char(ch)
            index += 1
            continue

        if ch == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            append_char(ch)
            index += 1
            continue

        if not in_single_quote and not in_double_quote:
            if next_two == "--":
                append_char(next_two)
                index += 2
                in_line_comment = True
                continue
            if next_two == "/*":
                append_char(next_two)
                index += 2
                in_block_comment = True
                continue
            if ch == "$":
                end = index + 1
                while (
                    end < length
                    and contents[end] not in {"$", "\n"}
                    and (contents[end].isalnum() or contents[end] == "_")
                ):
                    end += 1
                if end < length and contents[end] == "$":
                    tag = contents[index : end + 1]
                    append_char(tag)
                    index = end + 1
                    dollar_tag = tag
                    continue
            if ch == ";" and dollar_tag is None:
                append_char(ch)
                statement = "".join(current).strip()
                if statement:
                    statements.append(statement.rstrip(";"))
                current = []
                index += 1
                continue

        append_char(ch)
        index += 1

    trailing = "".join(current).strip()
    if trailing:
        statements.append(trailing)

    return [stmt for stmt in statements if stmt]


def run_sql_file(
    engine: Engine,
    sql_path: Path,
    parameters: Optional[Dict[str, Any]] = None,
) -> None:
    if not sql_path.exists():
        raise ConfigError(f"SQL file not found: {sql_path}")
    sql_text = sql_path.read_text(encoding="utf-8")
    statements = split_sql_statements(sql_text)
    if not statements:
        return
    params = parameters or {}
    with engine.begin() as conn:
        for statement in statements:
            clause = text(statement)
            bind_keys = list(getattr(clause, "_bindparams", {}).keys())
            if bind_keys:
                clause_params = {key: params[key] for key in bind_keys if key in params}
                missing = [key for key in bind_keys if key not in clause_params]
                if missing:
                    raise ConfigError(
                        f"Missing parameters {missing} for SQL script {sql_path}"
                    )
                conn.execute(clause, clause_params)
            else:
                conn.execute(clause)
    logger.info("Executed SQL script %s", sql_path)


@app.command("promote-core")
def promote_core(
    sql_path: Path = typer.Option(
        APP_DIR / "sql" / "promote_core.sql",
        "--sql-path",
        help="Path to promote_core.sql.",
    ),
    summary_sql: Path = typer.Option(
        APP_DIR / "sql" / "build_core_summaries.sql",
        "--summary-sql",
        help="Path to SQL that builds monthly summaries and aggregates.",
    ),
) -> None:
    """Promote staging data into the core.fact_goods_distributed table."""
    engine = load_engine()
    run_sql_file(engine, sql_path)
    run_sql_file(engine, summary_sql)


@app.command("build-analytics")
def build_analytics(
    analytics_sql: Path = typer.Option(
        APP_DIR / "sql" / "analytics.sql",
        "--sql-path",
        help="Path to analytics SQL script (legacy views).",
    ),
    item_month_sql: Path = typer.Option(
        APP_DIR / "sql" / "analytics_item_month_demand.sql",
        "--item-month-sql",
        help="Path to SQL that builds analytics.item_month_demand.",
    ),
    dim_month_sql: Path = typer.Option(
        APP_DIR / "sql" / "core_dim_month.sql",
        "--dim-month-sql",
        help="Path to SQL that maintains core.dim_month.",
    ),
    dim_item_sql: Path = typer.Option(
        APP_DIR / "sql" / "core_dim_item.sql",
        "--dim-item-sql",
        help="Path to SQL that maintains core.dim_item.",
    ),
    quality_sql: Path = typer.Option(
        APP_DIR / "sql" / "analytics_quality.sql",
        "--quality-sql",
        help="Path to SQL that builds analytics quality control objects.",
    ),
) -> None:
    """Create or refresh analytics-layer objects."""
    engine = load_engine()
    build_run_id = str(uuid.uuid4())
    logger.info("Starting analytics build (run_id=%s)", build_run_id)

    run_sql_file(engine, dim_month_sql)
    run_sql_file(engine, dim_item_sql)
    run_sql_file(engine, item_month_sql, {"build_run_id": build_run_id})
    run_sql_file(engine, analytics_sql)
    run_sql_file(engine, quality_sql)

    with engine.begin() as conn:
        item_count = (
            conn.execute(
                text("SELECT COUNT(*) FROM core.dim_item WHERE is_active")
            ).scalar()
            or 0
        )
        month_count = (
            conn.execute(text("SELECT COUNT(*) FROM core.dim_month")).scalar() or 0
        )
        demand_rows = (
            conn.execute(
                text(
                    "SELECT COUNT(*) FROM analytics.item_month_demand "
                    "WHERE build_run_id = :build_run_id"
                ),
                {"build_run_id": build_run_id},
            ).scalar()
            or 0
        )
        month_window = conn.execute(
            text(
                "SELECT MIN(month_start) AS min_month, MAX(month_start) AS max_month "
                "FROM analytics.item_month_demand"
            )
        ).mappings().one_or_none() or {"min_month": None, "max_month": None}

    logger.info(
        "Analytics build complete: %s active items, %s months, %s demand rows",
        item_count,
        month_count,
        demand_rows,
    )
    typer.echo(
        json.dumps(
            {
                "build_run_id": build_run_id,
                "active_item_count": item_count,
                "month_count": month_count,
                "demand_row_count": demand_rows,
                "month_range": {
                    "min": month_window["min_month"],
                    "max": month_window["max_month"],
                },
            },
            default=str,
        )
    )


@app.command("reset-data")
def reset_data(
    truncate_staging: bool = typer.Option(
        True,
        "--truncate-staging/--no-truncate-staging",
        help="Truncate stg.erp_goods_distributed.",
    ),
    truncate_core: bool = typer.Option(
        True,
        "--truncate-core/--no-truncate-core",
        help="Truncate core.fact_goods_distributed.",
    ),
    drop_analytics_view: bool = typer.Option(
        True,
        "--drop-analytics-view/--keep-analytics-view",
        help="Drop analytics.item_monthly_purchases view before rebuild.",
    ),
    truncate_item_month_demand: bool = typer.Option(
        True,
        "--truncate-demand/--keep-demand",
        help="Truncate analytics.item_month_demand table.",
    ),
    truncate_dim_tables: bool = typer.Option(
        False,
        "--truncate-dims/--keep-dims",
        help="Truncate core.dim_item and core.dim_month before rebuild.",
    ),
) -> None:
    """Remove previously loaded data to allow a fresh run."""
    engine = load_engine()
    with engine.begin() as conn:
        if truncate_staging and table_exists(engine, "stg.erp_goods_distributed"):
            conn.execute(text("TRUNCATE TABLE stg.erp_goods_distributed"))
            logger.info("Truncated stg.erp_goods_distributed")
        if truncate_core and table_exists(engine, "core.fact_goods_distributed"):
            conn.execute(text("TRUNCATE TABLE core.fact_goods_distributed"))
            logger.info("Truncated core.fact_goods_distributed")
        if drop_analytics_view:
            conn.execute(text("DROP VIEW IF EXISTS analytics.item_monthly_purchases"))
            logger.info("Dropped analytics.item_monthly_purchases")
        if truncate_item_month_demand and table_exists(
            engine, "analytics.item_month_demand"
        ):
            conn.execute(text("TRUNCATE TABLE analytics.item_month_demand"))
            logger.info("Truncated analytics.item_month_demand")
        if truncate_dim_tables:
            if table_exists(engine, "core.dim_item"):
                conn.execute(text("TRUNCATE TABLE core.dim_item"))
                logger.info("Truncated core.dim_item")
            if table_exists(engine, "core.dim_month"):
                conn.execute(text("TRUNCATE TABLE core.dim_month"))
                logger.info("Truncated core.dim_month")
    logger.info(
        "Reset complete. Run promote-core and build-analytics again after reload."
    )


def main() -> None:
    try:
        app()
    except ConfigError as exc:
        logger.error(str(exc))
        raise typer.Exit(code=1) from exc
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.exception("Unhandled error: %s", exc)
        raise typer.Exit(code=1) from exc


if __name__ == "__main__":
    main()
