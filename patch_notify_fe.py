from pathlib import Path
p = Path("/root/projects/ytb2bili-main/web/src/app/dashboard/settings/page.tsx")
s = p.read_text(encoding="utf8")

# 1) extend type
s = s.replace(
    "type SettingsSectionId = 'translation' | 'tts' | 'apiKeys' | 'system' | 'publishing' | 'template';",
    "type SettingsSectionId = 'translation' | 'tts' | 'apiKeys' | 'system' | 'notify' | 'publishing' | 'template';",
)

# 2) constants
s = s.replace(
    "const SYSTEM_SETTING_KEY_YOUTUBE_FEED_SYNC_LOOKBACK = 'youtube_feed_sync_lookback_days';",
    '''const SYSTEM_SETTING_KEY_YOUTUBE_FEED_SYNC_LOOKBACK = 'youtube_feed_sync_lookback_days';
const SYSTEM_SETTING_KEY_NOTIFY_ENABLED = 'notify_enabled';
const SYSTEM_SETTING_KEY_NOTIFY_WEBHOOK_URL = 'notify_webhook_url';
const SYSTEM_SETTING_KEY_NOTIFY_MAGICPUSH_URL = 'notify_magicpush_url';
const SYSTEM_SETTING_KEY_NOTIFY_NTFY_URL = 'notify_ntfy_url';
const SYSTEM_SETTING_KEY_NOTIFY_BARK_URL = 'notify_bark_url';''',
)

# 3) nav item
s = s.replace(
    "    { id: 'system', label: '系统设置', icon: SlidersHorizontal },",
    "    { id: 'system', label: '系统设置', icon: SlidersHorizontal },\n    { id: 'notify', label: '通知', icon: Bell },",
)

# 4) import Bell
if "Bell," not in s:
    s = s.replace("import {", "import { Bell,", 1)

# 5) state after youtubeFeedSyncLookback
s = s.replace(
    "  const [youtubeFeedSyncLookback, setYouTubeFeedSyncLookback] = useState('7');",
    '''  const [youtubeFeedSyncLookback, setYouTubeFeedSyncLookback] = useState('7');
  const [notifyEnabled, setNotifyEnabled] = useState(false);
  const [notifyWebhookURL, setNotifyWebhookURL] = useState('');
  const [notifyMagicPushURL, setNotifyMagicPushURL] = useState('');
  const [notifyNtfyURL, setNotifyNtfyURL] = useState('');
  const [notifyBarkURL, setNotifyBarkURL] = useState('');
  const [notifyTesting, setNotifyTesting] = useState(false);''',
)

# 6) load in getSettings then block
s = s.replace(
    """    setYouTubeFeedSyncEnabled(nextEnabled);
    setYouTubeFeedSyncInterval(nextInterval);
    setYouTubeFeedSyncLookback(nextLookback);
    setSystemSettingsLoaded(true);""",
    """    setYouTubeFeedSyncEnabled(nextEnabled);
    setYouTubeFeedSyncInterval(nextInterval);
    setYouTubeFeedSyncLookback(nextLookback);
    setNotifyEnabled(systemSettings[SYSTEM_SETTING_KEY_NOTIFY_ENABLED] === '1');
    setNotifyWebhookURL(systemSettings[SYSTEM_SETTING_KEY_NOTIFY_WEBHOOK_URL] ?? '');
    setNotifyMagicPushURL(systemSettings[SYSTEM_SETTING_KEY_NOTIFY_MAGICPUSH_URL] ?? '');
    setNotifyNtfyURL(systemSettings[SYSTEM_SETTING_KEY_NOTIFY_NTFY_URL] ?? '');
    setNotifyBarkURL(systemSettings[SYSTEM_SETTING_KEY_NOTIFY_BARK_URL] ?? '');
    setSystemSettingsLoaded(true);""",
)

# 7) reset defaults when no user
s = s.replace(
    """    setYouTubeFeedSyncInterval('60');
    setYouTubeFeedSyncLookback('7');
    setSystemSettingsError('');
    setSystemSettingsLoaded(false);""",
    """    setYouTubeFeedSyncInterval('60');
    setYouTubeFeedSyncLookback('7');
    setNotifyEnabled(false);
    setNotifyWebhookURL('');
    setNotifyMagicPushURL('');
    setNotifyNtfyURL('');
    setNotifyBarkURL('');
    setSystemSettingsError('');
    setSystemSettingsLoaded(false);""",
)

# 8) handlers after youtube feed enabled change
s = s.replace(
    """  const handleYouTubeFeedSyncIntervalChange""",
    """  const handleNotifyEnabledChange = useCallback((nextValue: boolean) => {
    setNotifyEnabled(nextValue);
    void systemSettingsApi.updateSettings({
      [SYSTEM_SETTING_KEY_NOTIFY_ENABLED]: nextValue ? '1' : '0',
    }).catch(() => {
      toast.error(translateClientText('保存通知开关失败'));
    });
  }, []);

  const persistNotifyField = useCallback((key: string, value: string) => {
    void systemSettingsApi.updateSettings({ [key]: value }).catch(() => {
      toast.error(translateClientText('保存通知配置失败'));
    });
  }, []);

  const handleNotifyTest = useCallback(async () => {
    setNotifyTesting(true);
    try {
      const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null;
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) headers.Authorization = `Bearer ${token}`;
      const res = await fetch('/api/v1/system/notify/test', {
        method: 'POST',
        headers,
        credentials: 'include',
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error((payload as { message?: string }).message || `HTTP ${res.status}`);
      }
      toast.success(translateClientText('测试通知已发送'));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : translateClientText('测试通知失败'));
    } finally {
      setNotifyTesting(false);
    }
  }, []);

  const handleYouTubeFeedSyncIntervalChange""",
)

# 9) UI section after system block - find publishing section and insert notify before it
old_pub = """                  {activeSection === item.id && item.id === 'publishing' && ("""
new_pub = """                  {activeSection === item.id && item.id === 'notify' && (
                    <div className="border-t border-slate-200">
                      <SettingsCardContent>
                        <SectionHint text={t('任务完成/失败时推送通知；可配通用 Webhook 或魔法推送 MagicPush。')} />
                        <SurfaceCard
                          title={t('推送开关')}
                          description={t('开启后才会向下方已配置的渠道发送通知。')}
                          tone="accent"
                        >
                          <SettingsRow
                            title={t('启用通知')}
                            description={t('关闭后不发送任何出站通知。')}
                          >
                            <Switch
                              checked={notifyEnabled}
                              disabled={systemSettingsLoading && !systemSettingsLoaded}
                              onChange={handleNotifyEnabledChange}
                            />
                          </SettingsRow>
                        </SurfaceCard>

                        <SurfaceCard
                          title={t('魔法推送 MagicPush')}
                          description={t('填写接口地址，通常为 http://主机:818/api/push/<TOKEN>')}
                        >
                          <SettingsRow title={t('MagicPush 接口')} description={t('支持本机 127.0.0.1:818')}>
                            <Input
                              value={notifyMagicPushURL}
                              placeholder="http://127.0.0.1:818/api/push/TOKEN"
                              disabled={systemSettingsLoading && !systemSettingsLoaded}
                              onChange={(e) => setNotifyMagicPushURL(e.target.value)}
                              onBlur={() => persistNotifyField(SYSTEM_SETTING_KEY_NOTIFY_MAGICPUSH_URL, notifyMagicPushURL)}
                              className="w-full max-w-md"
                            />
                          </SettingsRow>
                        </SurfaceCard>

                        <SurfaceCard
                          title={t('通用 Webhook')}
                          description={t('POST JSON：event/title/message/video_id/status')}
                        >
                          <SettingsRow title={t('Webhook URL')} description={t('任意可接收 JSON 的地址')}>
                            <Input
                              value={notifyWebhookURL}
                              placeholder="https://example.com/hooks/ytb2bili"
                              disabled={systemSettingsLoading && !systemSettingsLoaded}
                              onChange={(e) => setNotifyWebhookURL(e.target.value)}
                              onBlur={() => persistNotifyField(SYSTEM_SETTING_KEY_NOTIFY_WEBHOOK_URL, notifyWebhookURL)}
                              className="w-full max-w-md"
                            />
                          </SettingsRow>
                        </SurfaceCard>

                        <SurfaceCard
                          title={t('其他渠道（可选）')}
                          description={t('ntfy / Bark')}
                        >
                          <div className="space-y-3">
                            <SettingsRow title={t('ntfy URL')} description={t('例如 http://ntfy.example.com/topic')}>
                              <Input
                                value={notifyNtfyURL}
                                placeholder="http://127.0.0.1:8090/ytb2bili"
                                disabled={systemSettingsLoading && !systemSettingsLoaded}
                                onChange={(e) => setNotifyNtfyURL(e.target.value)}
                                onBlur={() => persistNotifyField(SYSTEM_SETTING_KEY_NOTIFY_NTFY_URL, notifyNtfyURL)}
                                className="w-full max-w-md"
                              />
                            </SettingsRow>
                            <SettingsRow title={t('Bark URL')} description={t('例如 https://api.day.app/KEY')}>
                              <Input
                                value={notifyBarkURL}
                                placeholder="https://api.day.app/KEY"
                                disabled={systemSettingsLoading && !systemSettingsLoaded}
                                onChange={(e) => setNotifyBarkURL(e.target.value)}
                                onBlur={() => persistNotifyField(SYSTEM_SETTING_KEY_NOTIFY_BARK_URL, notifyBarkURL)}
                                className="w-full max-w-md"
                              />
                            </SettingsRow>
                          </div>
                        </SurfaceCard>

                        <div className="flex items-center gap-3 pt-2">
                          <Button
                            variant="outline"
                            disabled={!notifyEnabled || notifyTesting}
                            onClick={() => { void handleNotifyTest(); }}
                          >
                            {notifyTesting ? t('发送中...') : t('发送测试通知')}
                          </Button>
                        </div>
                      </SettingsCardContent>
                    </div>
                  )}

                  {activeSection === item.id && item.id === 'publishing' && ("""
if old_pub not in s:
    raise SystemExit("publishing UI anchor not found")
s = s.replace(old_pub, new_pub, 1)
p.write_text(s, encoding="utf8")
print("frontend settings page patched")
