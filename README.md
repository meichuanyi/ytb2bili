# ytb2bili

<p align="center">
	<img src="web/public/logo.png" alt="ytb2bili logo" width="640" />
</p>

<p align="center">
	<a href="https://github.com/difyz9/ytb2bili/releases"><img alt="GitHub release" src="https://img.shields.io/github/v/release/difyz9/ytb2bili?display_name=tag" /></a>
	<a href="https://github.com/difyz9/ytb2bili/stargazers"><img alt="GitHub stars" src="https://img.shields.io/github/stars/difyz9/ytb2bili?style=social" /></a>
	<a href="https://github.com/difyz9/ytb2bili/blob/main/LICENSE"><img alt="License" src="https://img.shields.io/github/license/difyz9/ytb2bili" /></a>
	<a href="https://github.com/difyz9/ytb2bili/commits/main"><img alt="Last commit" src="https://img.shields.io/github/last-commit/difyz9/ytb2bili" /></a>
</p>

Language: [English](README.en.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [한국어](README.ko.md)

ytb2bili is a video workflow system for local video translation playback and YouTube-to-Bilibili publishing. It combines a Go backend, a Next.js web console, subtitle processing, AI copy generation, subtitle voice synthesis, synchronized audio/video playback, and Bilibili upload automation.

## Fork Enhancements (vs upstream)

> This repository is a fork of [difyz9/ytb2bili](https://github.com/difyz9/ytb2bili) with the following additions:

- **Task event notifications**: new `[notify]` config section and notifier service — push task completed/failed, Bilibili upload success/warning events to generic Webhook, ntfy, MagicPush, Bark, or Telegram; new "Notifications" section in the web settings page.
- **Full-video Chinese dubbing (DubAudio step)**: mixes per-subtitle TTS segments into the video audio track on the subtitle timeline (original audio ducked as background), wired into the main processing chain.
- **Edge TTS availability fix**: implements Microsoft's `Sec-MS-GEC` token and WebSocket protocol — upstream's plain REST calls were deprecated by Microsoft, this restores the free Edge voices.
- **Starts without LLM configured**: upstream fails to boot when the chat LLM is missing; this fork degrades to a warning and skips LLM-dependent features at runtime instead.
- **Download fallback retry**: when all download strategies fail (typically datacenter IPs being throttled to 360p by YouTube), retries once with relaxed minimum resolution instead of failing the whole pipeline.
- **Automatic retry of failed tasks**: a background cron job scans failed videos and reprocesses them up to a retry cap.
- **Self-hosted membership unlock**: local deployments unlock all membership tiers, avoiding features locked behind the removed membership backend.
- **Promo text in upload description off by default**: now appended only when explicitly enabled in settings.
- **YouTube OAuth via environment variables**: `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET` / `YOUTUBE_REDIRECT_URL` can override the config file; wired into docker-compose.
- **HTTP access log middleware**: structured request logging (includes Origin/Referer, never credential headers) with noise reduction for static assets.
- **Subtitle translation is now a required step**: LLM translation failures no longer pass silently; combined with notifications they are immediately visible.
- **Docs & tooling**: added a Chinese architecture document `docs/ARCHITECTURE.md` (layering, Step/Chain workflow model, end-to-end data flow) and a Whisper transcription helper script `tools/whisper_transcribe.py`.

## Overview

- Local video translation and review with subtitles, voiceover, and synchronized playback.
- End-to-end YouTube to Bilibili workflow: download, transcription, translation, metadata generation, upload, and subtitle upload.
- Task-based pipeline with configurable steps for downloading, audio extraction, transcription, translation, and publishing.
- Web console for task tracking, account linking, settings, retries, manual uploads, and assistant-driven operations.

## Read The Full README

- [English README](README.en.md)
- [简体中文 README](README.zh-CN.md)
- [日本語 README](README.ja.md)
- [한국어 README](README.ko.md)

## Quick Links

- [Documentation Index](docs/INDEX.md)
- [Configuration Example](config.toml.example)
- [Docker Test/Deployment Notes](docker/README.md)
- [Docker Development Guide](README.docker.md)
- [Project Guide](PROJECT_GUIDE.md)

## Community

If you want updates, troubleshooting help, or product discussion, you can reach out through the GitHub repository or scan the community QR codes below.

<p>
	<img src="img/220421_706.png" alt="QQ group QR code" width="280" />
	<img src="img/751763091471.jpg" alt="WeChat contact QR code" width="280" />
</p>

## Repository Layout

- `internal/`: backend application code, handlers, workflows, storage, and bootstrap logic.
- `pkg/`: reusable packages such as LLM integrations, tools, and shared models.
- `web/`: Next.js frontend for the management console.
- `configs/`: configuration examples and related notes.
- `docs/`: deployment, feature, architecture, and troubleshooting documentation.
- `docker/`: container build and runtime files.

## Local Development

```bash
cp config.toml.example config.toml
go run main.go

cd web
npm install
npm run dev
```

Default local URLs:

- Backend: `http://localhost:8096`
- Frontend: `http://localhost:3000`

## Build

```bash
make build
make build-linux-amd64
make test
```

## License

[MIT License](LICENSE)

## Contributing

Issues and pull requests are welcome.

## Contact

- GitHub: [@difyz9](https://github.com/difyz9)
- Repository: [https://github.com/difyz9/ytb2bili](https://github.com/difyz9/ytb2bili)
