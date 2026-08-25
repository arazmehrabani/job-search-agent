@echo off
cd /d %~dp0
conda run -n agent python agent.py run
