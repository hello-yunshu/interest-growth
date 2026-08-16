# Interest Growth — Android 安装指南

本文档面向用户。APK 只以 `android-remote` 运行时工作：数据保存在你自己的自托管服务器，Android 设备上不保存你的知识库数据。

> 当前 v0.7 只发布 **arm64-v8a** 的 universal release APK。下载前先核对下面的 SHA-256 和签名指纹，不要安装来源不明的文件。

## 1. 下载 APK

从可信来源获取 release APK，例如本仓库的发布物：

```
dist/android/interest-growth-0.7.0-universal-release.apk
```

## 2. 核对 SHA-256

在电脑上计算哈希，并与发布记录对比：

```bash
shasum -a 256 interest-growth-0.7.0-universal-release.apk
```

v0.7.0 release APK 的 SHA-256：

```
01ce82e4a2a03a6cca41a06fe15c3e1342bae0ee9f948afd02097c7499092024
```

哈希不一致说明文件被篡改或下载损坏，不要安装。

## 3. 核对签名指纹

安装前可用 Android 官方工具核对签名证书（无需安装即可验证）：

```bash
apksigner verify --verbose --print-certs interest-growth-0.7.0-universal-release.apk
```

v0.7.0 release 签名证书：

```
Signer #1 certificate DN:      CN=Interest Growth, OU=Interest Growth, O=Interest Growth, C=CN
Signer #1 certificate SHA-256: 66871e8685d5bd7c3cc719e0b2ea2b8af2809a7648e333b0fe493a0cf41aa66f
Signature scheme:              APK Signature Scheme v2 (RSA-2048)
```

升级安装必须使用同一证书签名的 APK，否则系统会拒绝覆盖安装。

## 4. 允许安装

Android 默认禁止安装未知来源应用。首次安装时：

1. 打开「设置 → 安全 → 安装未知应用」；
2. 允许来自你下载 APK 的应用（浏览器 / 文件管理器）；
3. 只对可信来源开启，安装后建议关闭。

## 5. 安装

在设备上打开 APK 文件并确认安装。安装完成后启动应用。

## 6. 输入自托管服务器地址

首次启动后进入「Self-hosted server」模式，输入你的服务器 **HTTPS** 地址：

- 必须是 `https://`（公网 / 局域网 / VPN 都走 HTTPS）；
- 不接受明文 HTTP；
- 不接受自签名证书；
- 无需输入本地任何路径。

应用会先探测服务器兼容性，再引导你进行 owner bootstrap 或设备登录。

## 7. 登录

- 首次设备：owner bootstrap（一次性）；
- 后续设备：设备登录（与桌面端同一个账户体系）。

登录后 refresh 凭证保存在 Android Keystore 中，不会进入 Web 存储、普通 SharedPreferences 或页面脚本。

## 8. 更新

发布新版本时，直接用**同一签名密钥**构建的 APK 覆盖安装即可：

- 不会卸载应用；
- 已保存的服务器地址与登录态会保留（数据在服务器侧）；
- 更新后首次启动会自动恢复远端会话。

## 重要说明

- **APK 不包含 Python。** Android 运行时永远是 `android-remote`，不携带本地 Core / 本地数据库。
- **数据保存在 self-hosted server。** 设备只保存服务器地址与加密后的 refresh 凭证；你的知识库 canonical 数据在服务器侧。
- **离线不允许修改。** 没有本地缓存写操作；网络不可用时连接状态进入 Offline / Reconnecting，不允许 mutation。
- **不会自动合并 desktop-local 数据。** 切换运行时不会合并本机数据，需要明确重启并各自保持独立数据集。
- **release key fingerprint** 见上文第 3 节；指纹不一致的安装包不要信任。

## 已知边界（v0.7）

- 当前环境尚未在 Android 模拟器或真机上完成安装/运行验证；本文档给出的是静态构建与签名验证结果，真机安装验证属于后续硬件边界。
- 仅 arm64-v8a；armeabi-v7a / x86_64 未发布。
