# Telegram-transcript-exporter

Export a Telegram **private chat / group / channel** via **Telethon** into a compact, token-efficient transcript format for LLM analysis.


## Installation

### Using pipx (recommended)

```bash
pipx install git+https://github.com/yarreg/telegram-transcript-exporter.git
```

After installation, the `telegram-transcript-exporter` command will be available globally.

### Using pip

```bash
pip install git+https://github.com/yarreg/telegram-transcript-exporter.git
```

### From source

```bash
git clone https://github.com/yarreg/telegram-transcript-exporter.git
cd telegram-transcript-exporter
pip install -e .
```


## Usage

The exporter writes a single UTF-8 `.txt` transcript file.

- By default, the output is saved to `./tg_transcript.txt` (current working directory).
- Override the output path with:
  - `--output <path>` — where to write the resulting transcript.

There are two common ways to run the exporter:

### 1) Use an existing Telegram export (JSON)

If you already exported a chat via Telegram (Desktop) and have a JSON file, you can feed that JSON directly to the tool and generate the `.txt` transcript without connecting to Telegram.

- Prepare the Telegram export in **JSON** format (Telegram Desktop → Export chat history → Format: JSON).
- Provide the exported JSON to the tool via:
  - `--input-json <path>` — path to the Telegram Desktop export JSON (typically `result.json`).

Example:
- `python <entrypoint>.py --input-json /path/to/telegram-export/result.json --output ./my_chat.txt`

This mode is useful when you cannot / do not want to provide API credentials or access Telegram from the machine running the exporter.

### 2) Connect to Telegram directly (Telethon)

To connect directly, you must provide Telethon credentials. They can be set either via environment variables or CLI arguments:

- `--api-id` (int) defaults to `TELEGRAM_API_ID`
- `--api-hash` (str) defaults to `TELEGRAM_API_HASH`
- `--session` (str) defaults to `TELEGRAM_SESSION_NAME` (default: `tg_session`)

Example (env):
- `TELEGRAM_API_ID=123456`
- `TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef`
- `TELEGRAM_SESSION_NAME=tg_session`
- `TELEGRAM_SESSION_STRING=...`

Example (CLI arguments):
- `python <entrypoint>.py --api-id 123456 --api-hash 0123... --session tg_session --output ./my_chat.txt`

Also you can limit the number of messages to export with:
- `--max-messages <N>` — export only the latest N messages (default: all messages)
-- `--from-date <YYYY-MM-DD>` — export messages starting from this date (inclusive)
-- `--to-date <YYYY-MM-DD>` — export messages up to this date (inclusive)

By default, the session is stored in a file named `<session>.session` in the current working directory. But you can also provide a TELEGRAM_SESSION_STRING environment variable containing the session string directly.

#### Target chat / group / channel

When exporting directly from Telegram, you also need to specify the **target** dialog (chat/group/channel). Supported target formats:

- `@username`
- `t.me/...` link
- numeric id
- dialog title (as shown in your Telegram dialog list)

(Use the tool’s `--help` to see whether your repo expects this as `--target <...>` or a positional argument.)

#### Search dialogs / peer hints (`--search`)

If you don’t know the exact target identifier, use:

- `--search "<query>"`

This searches dialogs (by title/username/name) and prints peer hints that you can copy into the next run as the target.


## Transcript format
The output is a single `.txt` file with the following structure:

- **Format header (one line)**  
  The very first line starts with `TG-TRANSCRIPT v1: ...` and briefly describes how to interpret the file.

- **CHAT**  
  `CHAT: <title> (id=<id>)`
  This line contains the chat title and its unique Telegram ID.

- **AUTHORS**  
  A space-indented list of all authors in the chat, using a short readable code per author:

```
AUTHORS:
  CODE=Full Display Name (@username) (telegram_user_id)
```

Example:

```
AUTHORS:
  Y=Yaroslav (@yarreg) (user2359141)
  V=Petr (@user_nickname2) (user129459331)
```

Notes:
- `CODE` is a short identifier used in the transcript body.
- `@username` may be missing if the account has no username or it is not available. If username is missing `none` is used. If username if present, it is shown with the `@` sign.
- telegram_user_id is the unique numeric ID of the user in Telegram.

- **LINKS**  
A space-indented deduplicated list of all URLs referenced in the chat:

```
LINKS:
  L1=[https://example.com/](https://example.com/)...
  L2=[https://another-link.com/](https://another-link.com/)...

```

In the transcript body, URLs are replaced with `[L#]`.
This section may be empty if no URLs are present or URL encoding may be disabled by `--no-link-encoding` flag.

- **BODY (transcript)**  
The actual conversation, grouped by day and written as “turns”:

- Date headers: `YYYY-MM-DD` (printed only when the day changes)
- Turn lines: `[HH:MM:SS][#MSGID] [CODE][OP][USER_OR_MSG_ID]:text...` 
  - `HH:MM:SS` is the message time in 24-hour format (UTC) SS is optional and may be added with `--include-seconds` flag
  - `MSGID` message id for reference this message in replies. This value is monotonically increasing within the chat.
  - `CODE` is the author code from the AUTHORS section
  - `OP` is optional and may be:
    - `↪` for forwarded messages
    - `↩` for replies
  - `USER_OR_MSG_ID` is:
    - `ORIGUSER` for forwards, where ORIGUSER is the original author's or channel code from the AUTHORS section
    - `MSGID` for replies, where MSGID is the original message ID being replied to (see above #MSGID)
  - `text...` is the message text, with URLs replaced by `[L#]` codes from the LINKS section or message contains new lines represented as separate lines starting with a space.
- You can merge consecutive messages from the same author within a time window (default 300 seconds) into a single turn. This can be adjusted with `--merge-window-seconds <seconds>` If new day starts, merging is not applied across days.

Example:
```
2015-09-08
21:40 V:[L1]
21:41#1 V:Test message.
21:45 Y↩1:Replied to your message.
21:50 V:One more message.
22:50 Y↪G:Forwarded message from channel G.
...
```

Merging example (with `--merge-window-seconds 600`):
```
...
21:40 V:[L1]
V:Test message.
Y:One more message.
22:50 Y:Continuing my thoughts here.
...
```

If one of user sent multiple messages within the merge window, their texts are concatenated with newlines:
```
21:40 V:[L1]
V:Test message.
 Another message within merge window.
 One more message.
Y:One more message.
22:50 Y:Continuing my thoughts here.
```

Media objeccts encoded as special codes:
 * Photo:📎(photo:IMG_1234.jpg)
 * Voice: 📎(voice:msg_77.ogg 00:12)
 * File: 📎(file:spec.pdf 2.3MB)
 * Video: 📎(video:vid_01.mp4 12.5MB)

 Example:
 ```
 21:40 V:Here is the document you asked for. 📎(file:spec.pdf 2.3MB)
 ```


## Known Issues

### Username is `none` for forwarded messages

When exporting forwarded messages, the username of the original author may appear as `none` in the AUTHORS section:

```
P=Pavel Durov (none) (channel1006503122)
```

**Causes:**

1. **JSON export (Telegram Desktop):** The Telegram Desktop export format does not include usernames for forwarded message sources — only the display name is available.

2. **Telethon (direct API):** For some forwarded messages, the Telegram API returns limited information about the original sender due to:
   - Privacy settings of the original author
   - The source being a private/closed channel
   - The original account being deleted or restricted

