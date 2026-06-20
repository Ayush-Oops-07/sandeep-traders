# Sandeep Traders — Render.com Deployment Guide

## STEP 1 — GitHub pe Code Upload karo

1. GitHub.com pe jaao → New repository banao
2. Name: sandeep-traders, Private rakho
3. Apne computer pe:
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/TUMHARA_USERNAME/sandeep-traders.git
   git push -u origin main

## STEP 2 — Render.com pe Account Banao

https://render.com → Sign up with GitHub

## STEP 3 — PostgreSQL Database Banao

New + → PostgreSQL:
  Name: sandeep-traders-db
  Database: sandeep_traders
  User: sandeep_user
  Plan: Free
→ Create Database

Database ban jaane ke baad "Internal Database URL" copy karke rakh lo.

## STEP 4 — Web Service Banao

New + → Web Service → GitHub repo select karo

Settings:
  Name: sandeep-traders
  Runtime: Python 3
  Build Command: pip install -r requirements.txt
  Start Command: gunicorn app:app --workers 2 --bind 0.0.0.0:$PORT --timeout 120
  Plan: Free

Environment Variables add karo:
  DATABASE_URL = (Step 3 ka Internal Database URL)
  SECRET_KEY   = MySuperSecret2025Sandeep
  FLASK_ENV    = production

→ Create Web Service

## STEP 5 — Done!

2-3 minute mein build ho jaayega.
URL milega: https://sandeep-traders.onrender.com

Login:
  admin   / Ayush@841440
  mandeep / Thawe@841440
  sandeep / Thawe@841440

NOTE: Free plan pe pehli request mein 30-60 sec lag sakta hai (cold start).

## STEP 6 — Products Fix (Existing Deployment ke liye ONE TIME karo)

Agar products search nahi aa rahe ya invoice save nahi ho raha, ye command run karo:

  curl -X POST https://sandeep-traders.onrender.com/api/admin/fix-products

Ya browser mein open karo:
  https://sandeep-traders.onrender.com/api/admin/fix-products  (POST request chahiye)

Ye Customer aur Shoper dono ke liye products seed kar dega aur null party_type fix karega.
# sandeep-traders
