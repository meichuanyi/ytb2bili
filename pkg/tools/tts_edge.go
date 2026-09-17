package tools

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/gorilla/websocket"
)

// ── Edge-TTS Engine (free, no API key) ───────────────────────────────────────
// Uses Microsoft Edge's free TTS WebSocket endpoint (same backend as Azure, no auth needed).
// 微软已废弃纯 REST 调用，并要求 Sec-MS-GEC 防护令牌，必须走 WebSocket 协议。
// Ref: https://github.com/rany2/edge-tts

const (
	edgeTTSEndpoint  = "wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1"
	edgeTrustedToken = "6A5AA1D4EAFF4E9FB37E23D68491D6F4"
	edgeGECVersion   = "1-143.0.3650.75"
	edgeOrigin       = "chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold"
	edgeUserAgent    = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0"
	edgeOutputFormat = "audio-24khz-96kbitrate-mono-mp3"
)

type EdgeTTSEngine struct {
	dialer *websocket.Dialer
}

func NewEdgeTTSEngine() *EdgeTTSEngine {
	return &EdgeTTSEngine{
		dialer: &websocket.Dialer{HandshakeTimeout: 15 * time.Second},
	}
}

func (e *EdgeTTSEngine) Name() string {
	return "edge"
}

// generateSecMSGECToken 生成微软要求的 Sec-MS-GEC 防护令牌：
// 当前 UTC 时间向下取整到 5 分钟窗口，转换为 Windows FILETIME（自 1601-01-01 起
// 的 100ns 单位）后拼接 TrustedClientToken 做 SHA256，输出大写十六进制。
func generateSecMSGECToken() string {
	seconds := time.Now().UTC().Unix()
	seconds -= seconds % 300
	const filetimeEpochOffset = 11644473600 // 1601-01-01 → 1970-01-01 秒数
	ticks := (seconds + filetimeEpochOffset) * 10_000_000
	sum := sha256.Sum256([]byte(fmt.Sprintf("%d%s", ticks, edgeTrustedToken)))
	return strings.ToUpper(hex.EncodeToString(sum[:]))
}

func edgeRandomHex(n int) string {
	b := make([]byte, n)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

// edgeTimestamp 输出 Edge 客户端使用的日期格式，例如：
// "Fri Nov 3 2017 12:18:22 GMT+0000 (Coordinated Universal Time)"。
func edgeTimestamp() string {
	return time.Now().UTC().Format("Mon Jan 2 2006 15:04:05 GMT+0000 (Coordinated Universal Time)")
}

// Voices returns common Edge-TTS supported voices.
// Edge-TTS reuses the Azure voice catalog.
func (e *EdgeTTSEngine) Voices(ctx context.Context, locale string) ([]VoiceInfo, error) {
	// Return a curated list of common voices
	commonVoices := []VoiceInfo{
		{ShortName: "zh-CN-XiaoxiaoNeural", DisplayName: "Xiaoxiao (Neural)", Locale: "zh-CN"},
		{ShortName: "zh-CN-YunxiNeural", DisplayName: "Yunxi (Neural)", Locale: "zh-CN"},
		{ShortName: "zh-CN-YunjianNeural", DisplayName: "Yunjian (Neural)", Locale: "zh-CN"},
		{ShortName: "zh-CN-XiaoyiNeural", DisplayName: "Xiaoyi (Neural)", Locale: "zh-CN"},
		{ShortName: "zh-CN-YunyangNeural", DisplayName: "Yunyang (Neural)", Locale: "zh-CN"},
		{ShortName: "zh-HK-HiuGaaiNeural", DisplayName: "HiuGaai (Neural)", Locale: "zh-HK"},
		{ShortName: "en-US-JennyNeural", DisplayName: "Jenny (Neural)", Locale: "en-US"},
		{ShortName: "en-US-GuyNeural", DisplayName: "Guy (Neural)", Locale: "en-US"},
		{ShortName: "en-US-AriaNeural", DisplayName: "Aria (Neural)", Locale: "en-US"},
		{ShortName: "en-GB-SoniaNeural", DisplayName: "Sonia (Neural)", Locale: "en-GB"},
		{ShortName: "ja-JP-NanamiNeural", DisplayName: "Nanami (Neural)", Locale: "ja-JP"},
		{ShortName: "ko-KR-SunHiNeural", DisplayName: "SunHi (Neural)", Locale: "ko-KR"},
	}

	if locale != "" {
		var filtered []VoiceInfo
		for _, v := range commonVoices {
			if strings.HasPrefix(strings.ToLower(v.Locale), strings.ToLower(locale)) {
				filtered = append(filtered, v)
			}
		}
		if len(filtered) > 0 {
			return filtered, nil
		}
	}
	return commonVoices, nil
}

func (e *EdgeTTSEngine) Synthesize(ctx context.Context, text, voice string, rate, volume, pitch float64) ([]byte, error) {
	if strings.TrimSpace(text) == "" {
		return nil, fmt.Errorf("edge-tts: text is empty")
	}
	if strings.TrimSpace(voice) == "" {
		voice = "zh-CN-XiaoxiaoNeural"
	}

	locale := "en-US"
	if len(voice) >= 5 {
		locale = voice[:5] // e.g. "zh-CN" from "zh-CN-XiaoxiaoNeural"
	}

	ssml := fmt.Sprintf(`<speak version='1.0' xml:lang='%s' xmlns='http://www.w3.org/2001/10/synthesis' xmlns:mstts='http://www.w3.org/2001/mstts'>
		<voice name='%s'>
			<prosody rate='%+.0f%%' volume='%+.0f%%' pitch='%+.0fHz'>%s</prosody>
		</voice>
	</speak>`, locale, voice, (rate-1)*100, volume-100, pitch, escapeSSML(text))

	wssURL := fmt.Sprintf("%s?TrustedClientToken=%s&Sec-MS-GEC=%s&Sec-MS-GEC-Version=%s&ConnectionId=%s",
		edgeTTSEndpoint, edgeTrustedToken, generateSecMSGECToken(), edgeGECVersion, edgeRandomHex(16))

	conn, _, err := e.dialer.DialContext(ctx, wssURL, http.Header{
		"Origin":          []string{edgeOrigin},
		"User-Agent":      []string{edgeUserAgent},
		"Pragma":          []string{"no-cache"},
		"Cache-Control":   []string{"no-cache"},
		"Accept-Encoding": []string{"gzip, deflate, br"},
		"Accept-Language": []string{"en-US,en;q=0.9"},
		"Cookie":          []string{"muid=" + strings.ToUpper(edgeRandomHex(16)) + ";"},
	})
	if err != nil {
		return nil, fmt.Errorf("edge-tts dial failed: %w", err)
	}
	defer conn.Close()

	// 服务端响应超时（尊重 ctx 已有的 deadline）
	deadline := time.Now().Add(90 * time.Second)
	if ctxDeadline, ok := ctx.Deadline(); ok && ctxDeadline.Before(deadline) {
		deadline = ctxDeadline
	}
	_ = conn.SetReadDeadline(deadline)

	// 1. 发送 speech.config
	configMsg := "X-Timestamp:" + edgeTimestamp() + "\r\n" +
		"Content-Type:application/json; charset=utf-8\r\n" +
		"Path:speech.config\r\n\r\n" +
		`{"context":{"synthesis":{"audio":{"metadataoptions":{"sentenceBoundaryEnabled":"false","wordBoundaryEnabled":"false"},"outputFormat":"` + edgeOutputFormat + `"}}}}`
	if err := conn.WriteMessage(websocket.TextMessage, []byte(configMsg)); err != nil {
		return nil, fmt.Errorf("edge-tts send config: %w", err)
	}

	// 2. 发送 SSML（二进制帧：2 字节大端头部长度 + 头部 + 正文）
	reqID := edgeRandomHex(16)
	ssmlHeader := "X-RequestId:" + reqID + "\r\n" +
		"Content-Type:application/ssml+xml\r\n" +
		"X-Timestamp:" + edgeTimestamp() + "Z\r\n" +
		"Path:ssml\r\n\r\n"
	frame := make([]byte, 2+len(ssmlHeader)+len(ssml))
	binary.BigEndian.PutUint16(frame[:2], uint16(len(ssmlHeader)))
	copy(frame[2:], ssmlHeader)
	copy(frame[2+len(ssmlHeader):], ssml)
	if err := conn.WriteMessage(websocket.BinaryMessage, frame); err != nil {
		return nil, fmt.Errorf("edge-tts send ssml: %w", err)
	}

	// 3. 读取音频分片，直到 turn.end
	var audio []byte
	for {
		msgType, data, err := conn.ReadMessage()
		if err != nil {
			return nil, fmt.Errorf("edge-tts read: %w", err)
		}
		if msgType == websocket.TextMessage {
			if strings.Contains(string(data), "Path:turn.end") {
				break
			}
			continue
		}
		if msgType == websocket.BinaryMessage && len(data) > 2 {
			headerLen := binary.BigEndian.Uint16(data[:2])
			if int(headerLen)+2 > len(data) {
				continue
			}
			if strings.Contains(string(data[2:2+headerLen]), "Path:audio") {
				audio = append(audio, data[2+headerLen:]...)
			}
		}
	}

	if len(audio) == 0 {
		return nil, fmt.Errorf("edge-tts: no audio data received")
	}
	return audio, nil
}
