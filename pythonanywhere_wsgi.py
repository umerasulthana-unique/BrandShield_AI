# Paste the contents of this file into your PythonAnywhere WSGI configuration file
# (Web tab > "WSGI configuration file"), replacing everything in it.
# Then change the three lines marked CHANGE ME.
import os, sys

USERNAME = "yourusername"                      # CHANGE ME: your PythonAnywhere username
os.environ["SECRET_KEY"] = "paste-a-long-random-text-here"   # CHANGE ME: 40+ random characters
os.environ["ADMIN_EMAIL"] = "you@example.com"  # CHANGE ME: your login email
os.environ["ADMIN_PASSWORD"] = "ChangeThisPassword123!"      # CHANGE ME: your login password
os.environ["ADMIN_NAME"] = "Admin"
os.environ["BRANDSHIELD_SECURE_COOKIES"] = "1"

PROJECT = f"/home/{USERNAME}/BrandShield_AI"
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from app import app as application  # noqa: E402
