# 🚀 Render Deployment Checklist

Follow these steps to deploy your MFB Forecasting API to Render:

## ✅ Pre-Deployment

- [x] Remove Vercel configuration files
- [x] Create Render configuration (`render.yaml`)
- [x] Update documentation
- [x] Commit changes to Git
- [ ] Push to GitHub: `git push origin main`

## ✅ Render Setup

1. **Create Render Account**
   - [ ] Go to https://dashboard.render.com/
   - [ ] Sign up with GitHub (recommended) or email
   - [ ] Verify your email address

2. **Connect Repository**
   - [ ] Click "New +" → "Blueprint"
   - [ ] Authorize Render to access your GitHub
   - [ ] Select your repository: `mfb-forecasting-api`
   - [ ] Render will detect `render.yaml` automatically
   - [ ] Click "Apply" to create the service

3. **Configure Environment Variables**
   - [ ] Set `DATABASE_URL` (your Neon PostgreSQL connection string)
   - [ ] Set `API_KEY` (auto-generated or create your own)
   - [ ] Set `ENVIRONMENT` to `production`
   - [ ] Set `ALLOWED_ORIGINS` (your frontend URL or `*` for testing)
   - [ ] Set `PIPELINE_AUTO_RUN` to `false` (unless you want auto-runs)

## ✅ Deployment

4. **Deploy Service**
   - [ ] Click "Create Web Service" or "Deploy"
   - [ ] Wait for build to complete (~5-10 minutes first time)
   - [ ] Check build logs for any errors

## ✅ Post-Deployment Testing

5. **Test Your Deployment**
   - [ ] Visit `https://your-service-name.onrender.com/health`
   - [ ] Should return: `{"status": "ok"}`
   - [ ] Visit `https://your-service-name.onrender.com/docs`
   - [ ] Verify Swagger UI loads correctly

6. **Test API Endpoints**
   ```bash
   # Test health endpoint (no auth required)
   curl https://your-service-name.onrender.com/health
   
   # Test authenticated endpoint
   curl -H "X-API-Key: YOUR_API_KEY" \
        https://your-service-name.onrender.com/api/forecast/runs/latest
   ```

## ✅ Optional: Keep Service Awake

7. **Set Up Uptime Monitoring** (prevents 15-min sleep)
   - [ ] Go to https://uptimerobot.com (free)
   - [ ] Create a new HTTP(s) monitor
   - [ ] URL: `https://your-service-name.onrender.com/health`
   - [ ] Interval: Every 5 minutes
   - [ ] Save monitor

## ✅ Update Frontend

8. **Update Frontend Configuration**
   - [ ] Update API base URL in your frontend
   - [ ] Change from Vercel URL to Render URL
   - [ ] Update CORS settings if needed
   - [ ] Test frontend ↔ API connection

## 🎉 Done!

Your API is now deployed on Render's free tier!

## 📝 Important Notes

- **Cold Starts**: Free tier services sleep after 15 minutes of inactivity. First request takes ~30 seconds.
- **Build Time**: Initial builds take 5-10 minutes. Subsequent builds are faster due to caching.
- **Logs**: View real-time logs in Render Dashboard → Your Service → Logs
- **Restart**: You can manually restart the service from the Render Dashboard if needed

## 🆘 Troubleshooting

### Build Failed
- Check Render build logs for errors
- Verify `requirements.txt` is correct
- Try manual rebuild: Dashboard → Manual Deploy → "Clear build cache & deploy"

### Service Won't Start
- Check that start command is correct: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Verify environment variables are set
- Check service logs for Python errors

### 503 Errors
- Service is probably sleeping (cold start)
- Wait 30-60 seconds and retry
- Set up UptimeRobot to prevent sleeping

### Database Connection Failed
- Verify `DATABASE_URL` is correct
- Check that Neon DB is awake (free tier sleeps too)
- Ensure Neon allows connections from Render IPs

## 📚 Resources

- Full Guide: `RENDER_DEPLOYMENT.md`
- Migration Notes: `MIGRATION_NOTES.md`
- Render Docs: https://render.com/docs
- Render Community: https://community.render.com

---

**Need Help?** Check the troubleshooting section in `RENDER_DEPLOYMENT.md`

