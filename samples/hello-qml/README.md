# Hello QML

A minimal qml-tier plugin. It adds one page, "Hello QML", to the Tool menu. It has no binary.

## Pack and release

Pack it with the plugin SDK's script:

```bash
python3 tools/vendor/pack_plugin.py samples/hello-qml --output hello-qml-1.0.0.zip
```

Publish the zip as a GitHub Release asset on this repo, with tag `hello-qml-v1.0.0`. Then put the
zip's SHA-256 and size in `plugins/io.github.jackhurley303.hello-qml.json`.

To release a new version, change `version` in `qgcplugin.json`, pack again, and add a new item to
`versions` in the entry. Never change an existing item.
