"""API token management endpoints for US #20."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.db import get_db_connection
from app.security import verify_api_key


class TokenCreateRequest(BaseModel):
    """Request to create a new API token."""
    name: str
    expires_days: int = 365  # Default 1 year


class TokenResponse(BaseModel):
    """API token response."""
    token_id: UUID
    name: str
    token: str | None = None  # Only returned on creation
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None
    is_active: bool


class TokenListResponse(BaseModel):
    """List of API tokens (without token values)."""
    token_id: UUID
    name: str
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None
    is_active: bool


router = APIRouter(
    prefix="/api/tokens",
    tags=["api-tokens"],
    dependencies=[Depends(verify_api_key)],
)


def _generate_token() -> str:
    """Generate a secure random API token."""
    return f"mfb_{secrets.token_urlsafe(32)}"


@router.post("/", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def create_token(
    request: TokenCreateRequest,
    connection: asyncpg.Connection = Depends(get_db_connection),
) -> TokenResponse:
    """
    Create a new API token for external access.
    
    This endpoint supports US #20: Secure Data Access API.
    """
    
    token_id = uuid4()
    token = _generate_token()
    expires_at = datetime.utcnow() + timedelta(days=request.expires_days)
    
    try:
        # Create tokens table if it doesn't exist
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS analytics.api_tokens (
                token_id UUID PRIMARY KEY,
                name TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                expires_at TIMESTAMP NOT NULL,
                last_used_at TIMESTAMP,
                is_active BOOLEAN NOT NULL DEFAULT TRUE
            )
            """
        )
        
        # Store token (in production, hash it!)
        await connection.execute(
            """
            INSERT INTO analytics.api_tokens (
                token_id, name, token_hash, created_at, expires_at, is_active
            )
            VALUES ($1, $2, $3, $4, $5, TRUE)
            """,
            token_id,
            request.name,
            token,  # In production: hash this with bcrypt
            datetime.utcnow(),
            expires_at,
        )
        
        return TokenResponse(
            token_id=token_id,
            name=request.name,
            token=token,  # Only returned on creation
            created_at=datetime.utcnow(),
            expires_at=expires_at,
            last_used_at=None,
            is_active=True,
        )
        
    except asyncpg.exceptions.PostgresError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create API token.",
        ) from exc


@router.get("/", response_model=list[TokenListResponse])
async def list_tokens(
    connection: asyncpg.Connection = Depends(get_db_connection),
) -> list[TokenListResponse]:
    """
    List all API tokens (without token values).
    
    This endpoint supports US #20: Secure Data Access API.
    """
    
    try:
        # Check if table exists
        table_exists = await connection.fetchval(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'analytics' 
                AND table_name = 'api_tokens'
            )
            """
        )
        
        if not table_exists:
            return []
        
        records = await connection.fetch(
            """
            SELECT 
                token_id, name, created_at, expires_at, last_used_at, is_active
            FROM analytics.api_tokens
            ORDER BY created_at DESC
            """
        )
        
        return [TokenListResponse(**dict(record)) for record in records]
        
    except asyncpg.exceptions.PostgresError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list API tokens.",
        ) from exc


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(
    token_id: UUID,
    connection: asyncpg.Connection = Depends(get_db_connection),
) -> None:
    """
    Revoke (deactivate) an API token.
    
    This endpoint supports US #20: Secure Data Access API.
    """
    
    try:
        result = await connection.execute(
            """
            UPDATE analytics.api_tokens
            SET is_active = FALSE
            WHERE token_id = $1
            """,
            token_id,
        )
        
        if result == "UPDATE 0":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Token not found.",
            )
            
    except asyncpg.exceptions.UndefinedTableError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found.",
        )
    except asyncpg.exceptions.PostgresError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to revoke API token.",
        ) from exc
