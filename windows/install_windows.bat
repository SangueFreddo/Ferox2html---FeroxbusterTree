@echo off
rem ==========================================================
rem  Ferox2html - crea l'icona sul Desktop (Windows)
rem ==========================================================
setlocal
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "TARGET=%ROOT%\windows\Ferox2html.bat"
set "ICON=%ROOT%\assets\icon.ico"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$d=[Environment]::GetFolderPath('Desktop');" ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Ferox2html.lnk'));" ^
  "$s.TargetPath=$env:TARGET; $s.IconLocation=$env:ICON + ',0'; $s.WorkingDirectory=$env:ROOT;" ^
  "$s.WindowStyle=7; $s.Description='Feroxbuster -> sito ad albero (stile DirBuster)'; $s.Save()"

if errorlevel 1 (
  echo [!] Non sono riuscito a creare il collegamento.
) else (
  echo [+] Icona "Ferox2html" creata sul Desktop.
  echo     Doppio clic per scegliere il file, oppure trascina i file di feroxbuster sopra l'icona.
)
pause
