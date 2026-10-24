# Free deploy on PythonAnywhere (no card needed)

Free plan: 1 web app at yourname.pythonanywhere.com, 512 MB permanent storage (SQLite data survives), no custom domain.
Free web apps expire after 1 month unless you press the "Run until 1 month from today" button on the Web tab. Do this monthly.

## A. In VS Code (on your computer)
1. File > Open Folder > `BrandShield_AI`.
2. Terminal > New Terminal, then:
   ```
   git init
   git add .
   git commit -m "BrandShield AI"
   ```
3. Create an empty repository on github.com (name it `BrandShield_AI`; public is easiest, since the free plan cannot use private-repo credentials easily).
4. Back in the terminal (use the URL GitHub shows you):
   ```
   git branch -M main
   git remote add origin https://github.com/YOURNAME/BrandShield_AI.git
   git push -u origin main
   ```
   Do not commit secrets: your password goes only into the PythonAnywhere WSGI file, never into the repo.

## B. On PythonAnywhere
1. Sign up free at pythonanywhere.com (choose the Beginner/free account).
2. **Consoles > Bash**:
   ```
   git clone https://github.com/YOURNAME/BrandShield_AI.git
   mkvirtualenv --python=/usr/bin/python3.12 brandshield
   cd BrandShield_AI
   pip install -r requirements.txt
   ```
   (If 3.12 is missing, use `python3.11` or `python3.10`.)
3. **Web > Add a new web app** > Manual configuration > pick the same Python version.
4. On the Web tab set:
   - **Virtualenv:** `/home/YOURUSERNAME/.virtualenvs/brandshield`
   - **Static files:** URL `/static/`, Directory `/home/YOURUSERNAME/BrandShield_AI/static`
5. Click the **WSGI configuration file** link, delete everything, paste the contents of `pythonanywhere_wsgi.py`, change the lines marked CHANGE ME, and save.
6. Click the green **Reload** button. Open `https://YOURUSERNAME.pythonanywhere.com`.
7. Sign in with your ADMIN_EMAIL and ADMIN_PASSWORD, then use **Team** to add people.

## Updating later
Change code in VS Code, then `git add . && git commit -m "update" && git push`.
On PythonAnywhere: Bash console > `cd BrandShield_AI && git pull`, then press **Reload** on the Web tab.

## Troubleshooting
- **Error page:** Web tab > Error log link shows the reason.
- **Cannot sign in:** the admin is created only on first start. To reset, delete `brandshield.db` in the Files tab, edit the WSGI file, and Reload.
- **Site says it expired:** press "Run until 1 month from today" on the Web tab.
- Free accounts allow 100 CPU-seconds a day for consoles and tasks; keep consoles closed when not needed.
