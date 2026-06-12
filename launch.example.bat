@echo off
title Submissions Advisor
cd /d "%~dp0"
call "C:\Users\YOUR_USERNAME\anaconda3\Scripts\activate.bat" submission_advisor
python launch_app.py
