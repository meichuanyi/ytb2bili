package service

import (
	"context"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/difyz9/ytb2bili/internal/config"
	"go.uber.org/zap"
	"golang.org/x/oauth2"
	"golang.org/x/oauth2/google"
	"google.golang.org/api/option"
	"google.golang.org/api/youtube/v3"
)

const defaultYouTubeAPIKey = "AIzaSyAS5ZTsMgLDw5xfUWQkOvTDIDu_LlZrWuU"

type YouTubeClientFactory struct {
	logger      *zap.Logger
	oauthConfig *oauth2.Config
	httpClient  *http.Client
	oauthCtx    context.Context
	apiKey      string
}

func NewYouTubeClientFactory(logger *zap.Logger, cfg *config.AppConfig) *YouTubeClientFactory {
	transport := &http.Transport{
		TLSHandshakeTimeout:   30 * time.Second,
		ResponseHeaderTimeout: 30 * time.Second,
		ExpectContinueTimeout: 10 * time.Second,
		IdleConnTimeout:       90 * time.Second,
	}

	if cfg != nil && cfg.Workflow.ProxyURL != "" {
		if proxyURL, err := url.Parse(cfg.Workflow.ProxyURL); err == nil {
			transport.Proxy = http.ProxyURL(proxyURL)
			logger.Info("YouTube OAuth 使用代理", zap.String("proxy", cfg.Workflow.ProxyURL))
		} else {
			logger.Warn("代理地址解析失败，不使用代理", zap.String("proxy_url", cfg.Workflow.ProxyURL), zap.Error(err))
		}
	}

	httpClient := &http.Client{
		Timeout:   60 * time.Second,
		Transport: transport,
	}

	// 从 [youtube] 配置注入真实 OAuth 凭据。
	// 之前这里把 ClientID/ClientSecret/RedirectURL 硬编码为空字符串，
	// 导致授权 URL 缺少 client_id、token 交换必然返回 invalid_client，YouTube 登录必坏。
	clientID := ""
	clientSecret := ""
	redirectURL := ""
	if cfg != nil {
		clientID = strings.TrimSpace(cfg.Youtube.ClientID)
		clientSecret = strings.TrimSpace(cfg.Youtube.ClientSecret)
		redirectURL = strings.TrimSpace(cfg.Youtube.RedirectURL)
	}

	oauthConfig := &oauth2.Config{
		ClientID:     clientID,
		ClientSecret: clientSecret,
		RedirectURL:  redirectURL,
		Scopes:       []string{youtube.YoutubeReadonlyScope},
		Endpoint:     google.Endpoint,
	}

	oauthCtx := context.WithValue(context.Background(), oauth2.HTTPClient, httpClient)

	if clientID == "" || clientSecret == "" || redirectURL == "" {
		logger.Warn("YouTube OAuth 凭据未完整配置（[youtube] client_id/client_secret/redirect_url），授权流程不可用")
	} else {
		logger.Info("YouTube OAuth 配置已加载", zap.String("redirect_url", redirectURL))
	}

	return &YouTubeClientFactory{
		logger:      logger,
		oauthConfig: oauthConfig,
		httpClient:  httpClient,
		oauthCtx:    oauthCtx,
		apiKey:      defaultYouTubeAPIKey,
	}
}

func (f *YouTubeClientFactory) OAuthConfig() *oauth2.Config {
	if f == nil {
		return nil
	}
	return f.oauthConfig
}

// IsConfigured 报告 OAuth 凭据（client_id/client_secret/redirect_url）是否完整配置。
// oauthConfig 始终非 nil（未配置时各字段为空），调用方需用此方法区分
// “未配置”与“已配置”，避免用空凭据生成授权 URL / 交换 token。
func (f *YouTubeClientFactory) IsConfigured() bool {
	if f == nil || f.oauthConfig == nil {
		return false
	}
	return f.oauthConfig.ClientID != "" &&
		f.oauthConfig.ClientSecret != "" &&
		f.oauthConfig.RedirectURL != ""
}

func (f *YouTubeClientFactory) OAuthContext() context.Context {
	if f == nil || f.oauthCtx == nil {
		return context.Background()
	}
	return f.oauthCtx
}

func (f *YouTubeClientFactory) RedirectURL() string {
	if f == nil || f.oauthConfig == nil {
		return ""
	}
	return f.oauthConfig.RedirectURL
}

func (f *YouTubeClientFactory) AuthCodeURL(state string, opts ...oauth2.AuthCodeOption) string {
	if f == nil || f.oauthConfig == nil {
		return ""
	}
	return f.oauthConfig.AuthCodeURL(state, opts...)
}

func (f *YouTubeClientFactory) Exchange(ctx context.Context, code string) (*oauth2.Token, error) {
	if ctx == nil {
		ctx = f.OAuthContext()
	}
	return f.oauthConfig.Exchange(ctx, code)
}

func (f *YouTubeClientFactory) NewOAuthService(ctx context.Context, token *oauth2.Token) (*youtube.Service, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	client := f.oauthConfig.Client(ctx, token)
	return youtube.NewService(ctx, option.WithHTTPClient(client))
}

func (f *YouTubeClientFactory) NewAPIService(ctx context.Context) (*youtube.Service, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	return youtube.NewService(ctx, option.WithAPIKey(f.apiKey))
}
