-- 导出 PPTX 为 PDF（带等待与重试；PowerPoint 刚启动时容易报 -50）
-- 用法： osascript ppt/export_pdf.applescript <in.pptx> <out.pdf>
on run argv
	set inPath to POSIX file (item 1 of argv)
	set outPath to POSIX file (item 2 of argv)
	tell application "Microsoft PowerPoint"
		open inPath
		repeat 40 times
			if (count of presentations) > 0 then exit repeat
			delay 0.5
		end repeat
		delay 2
		set pres to presentation 1
		set ok to false
		repeat 8 times
			try
				save pres in outPath as save as PDF
				set ok to true
				exit repeat
			on error
				delay 2
			end try
		end repeat
		delay 1
		try
			close pres saving no
		end try
		if ok then
			return "exported"
		else
			error "PowerPoint 导出 PDF 失败"
		end if
	end tell
end run
