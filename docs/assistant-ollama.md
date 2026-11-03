# Built-in assistant with Ollama

Clipcura can use a model on your own [Ollama](https://ollama.com) server. You give it tasks in plain words on
the **Assistant** screen, and it uses the tools an MCP assistant gets, with the same limits.
Clipcura runs the tool loop itself, so there is nothing else to install.

## What goes where

- Clipcura connects **out** to the Ollama server. Its own API stays on `127.0.0.1` and is never opened to the
  network.
- Clipcura sends the conversation: your task, plus file names, paths, measured values and the tool results.
  Video and audio data are never sent.
- The model calls tools as actor `ai`:
  - conversions wait in **AI activity** for your approval (while the approval mode is on);
  - it cannot change settings or allowed folders;
  - it cannot approve its own requests.
- Every tool call appears as a step in the conversation and in the log.
- Models whose name ends in `cloud` run on ollama.com, not on your server. Settings warns about them.

## Setting it up

1. Open **Settings → Assistant (Ollama)**.
2. Enter the server address, for example `https://ollama.example.com`, and the access key if your server needs
   one.
3. Press **Test connection**. The list shows only models that can call tools.
4. Choose a model and turn on **Use the assistant**.

Models compared on the same task (check a folder, prepare the fixes, start them), November 2026:

| Model | Result |
|---|---|
| `qwen3.8:27b` | All steps, the most complete answer (41 s) |
| `qwen3.6:27b` | All steps (50 s) |
| `gemma4:26b` | All steps (34 s) |
| `nemotron-3.5-lightning:30b` | Once correct, once broke the folder path |
| `gpt-oss:20b` | Lost a backslash in the path, then fixed it after Clipcura said the folder does not exist (29 s) |
| `qwen3.5:9b` | Did not start the conversions, but said they were waiting for approval |

Use a model of about 25B parameters or more. Smaller models skip steps or describe things they did not do.
The same model can behave differently from run to run, so watch the steps it shows.

**Explain** appears next to a failed job and next to warnings and errors on the Log screen. It opens a
conversation that already contains the details: the error, the end of the FFmpeg output, and the file's measured
values and findings.

## An access key for Ollama

Ollama has no access keys of its own, and by default anyone who can reach port 11434 can use it, including
`/api/pull` and `/api/delete`. Put a reverse proxy in front of it that checks a key. Clipcura sends the key as
`Authorization: Bearer <key>`.

Example with [Caddy](https://caddyserver.com) (the server name and key are placeholders):

```caddyfile
ollama.example.com {
	@authorized header Authorization "Bearer {env.OLLAMA_PROXY_KEY}"
	handle @authorized {
		reverse_proxy 127.0.0.1:11434
	}
	respond 401
}
```

Example with nginx:

```nginx
server {
    listen 443 ssl;
    server_name ollama.example.com;
    # ssl_certificate ... / ssl_certificate_key ...

    location / {
        if ($http_authorization != "Bearer CHANGE-ME-LONG-RANDOM-KEY") { return 401; }
        proxy_pass http://127.0.0.1:11434;
        proxy_buffering off;        # replies are streamed
        proxy_read_timeout 600s;    # loading a large model can take minutes
    }
}
```

Bind Ollama itself to `127.0.0.1` (`OLLAMA_HOST=127.0.0.1:11434`) so that it can only be reached through the
proxy. Generate the key with, for example, `openssl rand -base64 32`.
