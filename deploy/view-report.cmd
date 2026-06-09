@echo off
REM Open the middler backcast report from the NAS share in your default browser.
REM The NAS rewrites this file every hour while middler runs, so it's always current.
REM Double-click this file, or pin it to your taskbar.

set "REPORT=\\KieranNAS\docker\middler\reports\backcast.html"
if exist "%REPORT%" (
    start "" "%REPORT%"
    goto :eof
)

REM Fall back to the IP if the NAS hostname doesn't resolve.
set "REPORT=\\192.168.4.42\docker\middler\reports\backcast.html"
if exist "%REPORT%" (
    start "" "%REPORT%"
    goto :eof
)

echo Could not find the report on the NAS share yet.
echo Once middler has run a cycle it appears at:
echo   \\KieranNAS\docker\middler\reports\backcast.html
pause
