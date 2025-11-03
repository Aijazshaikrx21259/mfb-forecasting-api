"""Vercel serverless entry point for the MFB Forecasting API."""

from app.main import app

# Vercel will use this app instance
handler = app
