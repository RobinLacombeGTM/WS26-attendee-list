# Web Summit attendee list: a Claude skill

Build your own list of Web Summit attendees, narrowed to the companies and roles you sell to, with each target's company website, company LinkedIn page and personal LinkedIn profile. Made for the follow-up after Web Summit Lisbon 2026.

You don't need to write code. Claude runs the steps and asks you for two things: your Web Summit login in your own browser, and who you want to reach.

## What you need

- Claude Code (desktop app, terminal or VS Code extension). https://claude.com/claude-code
- Python 3 on your computer (Claude checks and installs the one missing package).
- Your own Web Summit ticket and login.
- Chrome, Edge or Brave.

## Install

Pick one of three ways.

**Ask Claude.** Open Claude Code and paste:

> Install this skill with git clone: https://github.com/RobinLacombeGTM/WS26-attendee-list into ~/.claude/skills/websummit-attendee-list

Claude asks your permission before writing into `~/.claude/`. Approve it.

**One command.** In a terminal:

```
git clone https://github.com/RobinLacombeGTM/WS26-attendee-list ~/.claude/skills/websummit-attendee-list
```

**Without git.** Download [websummit-attendee-list.zip](https://github.com/RobinLacombeGTM/WS26-attendee-list/releases/latest/download/websummit-attendee-list.zip), unzip it, and move the `websummit-attendee-list` folder into `~/.claude/skills/` (on Windows: `%USERPROFILE%\.claude\skills\`). Create the folder if needed.

Then open Claude Code in an empty folder and type: **Build my Web Summit attendee list**.

Want to check the code first? [AUDIT.md](AUDIT.md) lists every place the code sends data and every safeguard, with line numbers, plus a test suite you can run in one command.

## What happens

1. Claude shows you how to copy your Web Summit session from the browser (about 1 minute). The session goes straight into a local file and never into the chat.
2. You pick the attendee types you care about (exhibitors, speakers, everyone). Claude exports that part of the directory you can already browse in the attendee portal: about 15 minutes for exhibitors and speakers, about 55 minutes for everyone, one request every 2.5 seconds.
3. You say who you want to reach: your ICP (industries, countries, exhibitors) and personas (roles, titles). Claude narrows the list to 50 to 300 people.
4. Claude finds the company websites and LinkedIn pages with web search. For personal LinkedIn profiles (Web Summit hides them), web search alone finds few: a free Firecrawl account does much better, and Claude shows the cost before using it. A profile counts as found only when the search result shows both the person's name and their company. The rest is marked for a quick manual check.
5. You get a spreadsheet (`enriched.csv`) with a status and the evidence for every link.

Recommended for personal profiles: a free Firecrawl account (firecrawl.dev, 1,000 free credits, about 500 searches). Apify and Hunter.io also work. Claude shows the cost first and waits for your yes.

## Built-in safeguards

- Uses your own ticket only. Claude refuses a colleague's login or a shared account.
- One request every 2.5 seconds, a fixed request budget you approve, and a full stop if Web Summit refuses, asks to slow down or shows a security check. No retries around a block.
- Your session is never printed or sent anywhere except to Web Summit. Claude deletes the file after the export.
- Nothing is uploaded, and nobody is contacted. The skill builds a list. Reaching out is up to you.

## Responsible use

The list holds personal data from the Web Summit directory. Use it for your own follow-up. Don't resell or publish it, honor anyone who asks not to be contacted, and delete it when you no longer need it. Check the Web Summit platform terms before you run the export. This skill is not affiliated with or endorsed by Web Summit. You run it at your own risk.

## Who made this

Robin Lacombe, Profitable Events. I run pre-event outreach and follow-up campaigns for B2B tech exhibitors. If you'd rather have the follow-up run for you: https://profitable-events.com/wet-summit/
