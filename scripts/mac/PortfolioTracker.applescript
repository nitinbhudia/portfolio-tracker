-- Portfolio Tracker for macOS: a stay-open applet that runs the app without a Terminal window.
-- Built on your Mac by scripts/mac/build-app.sh, which fills in the folder below. Quit it to stop the app.
-- It keeps no state of its own (that lives in the app folder's .run/), so the app bundle is never modified.
-- (No properties or globals: the applet then has nothing to save back into itself.)

on appHome()
	return "__APP_HOME__"
end appHome

on helper(cmd)
	return do shell script "/bin/bash " & quoted form of (my appHome() & "/scripts/mac/app.sh") & " " & cmd
end helper

on run
	try
		do shell script "test -f " & quoted form of (my appHome() & "/scripts/dev.sh")
	on error
		display dialog "Portfolio Tracker's folder wasn't found at:" & return & my appHome() & return & return & "If you moved or renamed it, open the folder and double-click Make Mac App again." buttons {"OK"} default button 1 with icon stop
		quit
		return
	end try
	try
		if helper("status") is "ready" then
			helper("open")
		else
			helper("start")
			display notification "Starting. The first start, and the first after an update, takes a few minutes." with title "Portfolio Tracker"
		end if
	on error errMsg
		display dialog "Portfolio Tracker couldn't start:" & return & errMsg buttons {"OK"} default button 1 with icon stop
		quit
	end try
end run

on idle
	try
		set s to helper("tick")
	on error
		return 5
	end try
	if s is "open-now" then
		helper("open")
	else if s is "failed" then
		set logTail to ""
		try
			set logTail to helper("tail 12")
		end try
		set r to display dialog "Portfolio Tracker stopped with an error. The last lines of its log:" & return & return & logTail buttons {"Open log", "Quit"} default button 2 with icon caution
		if button returned of r is "Open log" then helper("log")
		quit
	else if s is "stopped" then
		quit
	else if s is "slow" then
		set r to display dialog "Portfolio Tracker is taking unusually long to start (over 20 minutes)." buttons {"Open log", "Keep waiting"} default button 2
		if button returned of r is "Open log" then helper("log")
	end if
	return 3
end idle

on reopen
	try
		if helper("status") is "ready" then
			helper("open")
		else
			display notification "Still starting." with title "Portfolio Tracker"
		end if
	end try
end reopen

on quit
	try
		display notification "Stopping." with title "Portfolio Tracker"
		helper("stop")
	end try
	continue quit
end quit
