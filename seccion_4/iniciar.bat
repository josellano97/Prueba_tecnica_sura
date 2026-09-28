@echo off
rem Doble clic para preparar y abrir la aplicacion (llama a iniciar.ps1). Para abrirla en la red: iniciar.bat -Red
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0iniciar.ps1" %*
pause
