@echo off
title Submissions Advisor
call "C:\Users\YOUR_USERNAME\anaconda3\Scripts\activate.bat" submission_advisor
streamlit run "%~dp0app.py"
