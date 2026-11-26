@echo off
rem ==========================================================
rem  Ferox2html - avvio rapido per Windows
rem  Doppio clic  = si apre la finestra per scegliere il file
rem  Trascina uno o piu' file di feroxbuster qui sopra = report subito
rem ==========================================================
setlocal
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "SCRIPT=%ROOT%\ferox2html.py"

where pyw >nul 2>nul
if not errorlevel 1 goto run_pyw
where pythonw >nul 2>nul
if not errorlevel 1 goto run_pythonw

echo [!] Python non trovato.
echo     Installalo da https://www.python.org/downloads/
echo     e durante l'installazione spunta "Add python.exe to PATH".
pause
exit /b 1

:run_pyw
start "" pyw -3 "%SCRIPT%" --gui %*
exit /b 0

:run_pythonw
start "" pythonw "%SCRIPT%" --gui %*
exit /b 0
