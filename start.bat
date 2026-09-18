@echo off
rem ===========================================================================
rem  DEPRECATED LAUNCHER -- this repo has been merged into the monorepo.
rem
rem  This repository (tcms-ai-platform) is frozen. Its web UI is the build from
rem  2026-09-12 and does NOT contain later work: the runtime white-box stream,
rem  model selection with connectivity self-check, and the whole-site UI rework.
rem
rem  Letting it silently start the old build is a trap: the UI looks similar and
rem  the default port is the same (8000), so you end up judging the new work by
rem  an old copy without any hint that you are doing so.
rem
rem  This stub only shows a notice and offers to launch the real one. The notice
rem  text lives in an UTF-8-with-BOM .ps1 on purpose: cmd.exe parses .bat by the
rem  OEM codepage, so Chinese text written here would show up as mojibake.
rem
rem  The original launcher is kept as start.old.bat if you really need it.
rem ===========================================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0_legacy_notice.ps1"
