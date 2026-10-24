# Deploy BrandShield AI on Render

Cost: about $7/month (Starter) plus about $0.25/month for the 1 GB disk. Check render.com/pricing for current prices.

Why paid? Render's free web services cannot attach a disk, so SQLite data (users, drafts, decisions) would be erased on every restart. Free is fine only for a throwaway test.

## 1. Put the code on GitHub
1. Create a free account at github.com and a **new private repository** named `brandshield-ai`.
2. Unzip this project. On the repository page choose **Add file > Upload files**, drag in everything from inside the `BrandShield_AI` folder (not the folder itself), and **Commit**.

## 2. Create the service on Render
1. Sign up at render.com with your GitHub account.
2. Click **New > Blueprint**, pick your `brandshield-ai` repository, and continue. Render reads `render.yaml` and sets up the web service, disk and secret key for you.
3. When asked, fill in:
   - `ADMIN_EMAIL` - your login email
   - `ADMIN_PASSWORD` - a strong password (12+ characters)
   - `ADMIN_NAME` - your name
4. Click **Apply**. The first build takes a few minutes.

## 3. Open your site
Render shows a URL like `https://brandshield-ai.onrender.com`. Open it, click **Sign in**, and use the admin email and password you set.

Check `https://YOUR-URL/api/health` shows `"status": "ok"`.

## 4. Add your team
Sign in as admin, open **Team**, add people with a role and temporary password, and send them the site link and password privately.

## Custom domain (optional)
Render dashboard > your service > **Settings > Custom Domains**, add your domain, and create the DNS record Render shows you.

## If something goes wrong
- **Build fails:** open the **Logs** tab; confirm `requirements.txt` and `app.py` are at the top level of the repository.
- **Cannot sign in:** `ADMIN_EMAIL` and `ADMIN_PASSWORD` are used only when the database is empty. If you changed them after first start, sign in with the original values or add users from **Team**.
- **Data disappeared:** the disk is missing; confirm the service shows a disk mounted at `/var/data` and `BRANDSHIELD_DB` is `/var/data/brandshield.db`.

## Backups
In the Render **Shell** tab run `cp /var/data/brandshield.db /var/data/backup-$(date +%F).db` before big changes, and download copies occasionally.

## Doing it without the Blueprint
New > Web Service > your repo. Build command `pip install -r requirements.txt`. Start command `gunicorn app:app --workers 1 --threads 4`. Add a disk at `/var/data`, then set the environment variables listed in `.env.example`.
