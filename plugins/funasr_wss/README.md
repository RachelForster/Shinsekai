# FunASR WSS

Shinsekai ASR plugin for a self-hosted FunASR WebSocket service.

## Manifest entry

Add to `data/config/plugins.yaml`:

```yaml
- entry: plugins.funasr_wss.plugin:FunASRWssPlugin
  enabled: true
```

Then restart Shinsekai.

## Dependencies

This plugin expects a websocket client package:

```bash
pip install -r plugins/funasr_wss/requirements.txt
```

Or use the in-app plugin dependency installer after the plugin is present locally.

## Initial config

Recommended first-run values:

- `host`: `127.0.0.1`
- `port`: `10096`
- `use_ssl`: `false`
- `mode`: `2pass`
