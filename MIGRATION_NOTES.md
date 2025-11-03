# Migration from Vercel to Render

## Date
November 3, 2025

## Reason for Migration
Vercel's serverless functions have a hard 250 MB unzipped size limit. Our MFB Forecasting API uses data science libraries that exceed this limit:
- `pandas` (~100 MB)
- `numpy` (~50 MB)  
- `scipy` (~90 MB)
- `statsforecast` (~40 MB)

**Total package size**: ~280+ MB (exceeds Vercel's 250 MB limit)

## Changes Made

### Files Removed
- `vercel.json` - Vercel configuration file
- `.vercelignore` - Vercel ignore patterns
- `api/index.py` - Vercel serverless function entry point
- `.vercel/` directory - Vercel project metadata

### Files Added
- `render.yaml` - Render Blueprint configuration for automated deployment
- `RENDER_DEPLOYMENT.md` - Comprehensive deployment guide for Render
- `MIGRATION_NOTES.md` - This file

### Files Modified
- `README.md` - Updated deployment instructions from Vercel to Render
- `.gitignore` - Updated to include standard Python ignores

## Deployment Platform Comparison

| Feature | Vercel | Render (Free) |
|---------|---------|---------------|
| Function Size Limit | 250 MB | No limit (uses Docker) |
| Cold Start | ~5 seconds | ~30 seconds |
| Always On | Yes (Hobby+) | No (sleeps after 15min) |
| Monthly Cost | $20+ for Pro | Free |
| Database Support | External only | Built-in PostgreSQL available |
| ML/Data Science | ❌ Limited | ✅ Full support |

## Next Steps

1. **Push changes to GitHub**
   ```bash
   git push origin main
   ```

2. **Deploy to Render**
   - Visit https://dashboard.render.com/
   - Create New → Blueprint
   - Connect your repository
   - Render auto-detects `render.yaml`
   - Add environment variables
   - Deploy!

3. **Configure Environment Variables**
   - `DATABASE_URL` - Your Neon PostgreSQL connection string
   - `API_KEY` - Auto-generated or set manually
   - `ENVIRONMENT` - Set to "production"
   - `ALLOWED_ORIGINS` - Your frontend domain

4. **Test Deployment**
   ```bash
   curl https://your-service.onrender.com/health
   ```

5. **Optional: Keep Service Awake**
   Use UptimeRobot or Cron-job.org to ping your `/health` endpoint every 5-10 minutes to prevent sleeping.

## Rollback Plan (If Needed)

If you need to revert to Vercel for any reason:

```bash
git revert HEAD
git push origin main
```

Then redeploy to Vercel using the previous configuration.

## Support & Documentation

- Render Documentation: https://render.com/docs
- Render Community: https://community.render.com
- Project README: `README.md`
- Deployment Guide: `RENDER_DEPLOYMENT.md`

## Notes

- The Docker setup (`Dockerfile` and `compose.yaml`) remains unchanged and can still be used for local development
- All API endpoints and functionality remain exactly the same
- No code changes were required - only deployment configuration

