# Four-city EV charging data · 2026

**北京、上海、深圳、重庆充电站占用数据：原始数据镜像、清洗面板与下载工具。**

This is an **unofficial mirror and independently cleaned derivative**, not the original author's repository. The original dataset is by **Yu ruotao**, published on **2026-07-08** under **CC BY 4.0**. Please cite and credit the original source.

- Original dataset: [Figshare, DOI 10.6084/m9.figshare.32917595.v1](https://doi.org/10.6084/m9.figshare.32917595.v1)
- Original project: [yuruotao/chongqing_charging_data](https://github.com/yuruotao/chongqing_charging_data)
- **Actual data downloads:** [GitHub Release v1.0.0](https://github.com/zelin-michael-zhu/ev-charging-four-cities-2026/releases/tag/v1.0.0)
- Derivative cleaning date: **2026-10-19**. Changes and limitations: [data quality](docs/data_quality.md).

## 数据下载

### 清洗版：推荐用于分析

每城一个压缩包，包含 `panel.npz`、`panel.parquet`、`station_quality.parquet` 及精简 `station_meta.csv`。下载入口：

- [北京](https://github.com/zelin-michael-zhu/ev-charging-four-cities-2026/releases/download/v1.0.0/cleaned-beijing.tar.gz)
- [上海](https://github.com/zelin-michael-zhu/ev-charging-four-cities-2026/releases/download/v1.0.0/cleaned-shanghai.tar.gz)
- [深圳](https://github.com/zelin-michael-zhu/ev-charging-four-cities-2026/releases/download/v1.0.0/cleaned-shenzhen.tar.gz)
- [重庆](https://github.com/zelin-michael-zhu/ev-charging-four-cities-2026/releases/download/v1.0.0/cleaned-chongqing.tar.gz)

Python 3.10+，下载和校验工具仅依赖标准库：

```bash
python scripts/download_data.py --city beijing --extract
python scripts/verify_data.py
```

默认下载全部四城；可用 `--city beijing shanghai` 限定范围。详细用法及读取示例见 [usage](docs/usage.md) 和 [字段说明](docs/data_dictionary.md)。

### 原始包：完整保留上游字节

原始 `data.zip` 为 **4,547,739,657 bytes**。Release 将其按顺序分为四卷，方便在 GitHub 下载：

```bash
python scripts/download_data.py --kind raw
```

工具会校验分卷并重组 `data.zip`；也可手动按 `part01`、`part02`、`part03`、`part04` 的顺序拼接。

- Original MD5: `1b7d7f2ba81f3b9d1b06d4d77a6533d9`
- Original SHA256: `43cc0ce420d1e8b8b9557e4387a68a86da11c338287c599f52129bda5e3888c5`
- [Official upstream download](https://ndownloader.figshare.com/files/66387119)

所有文件的大小和 SHA256 见 [release manifest](data/releases.json)；解压后文件的哈希见 [cleaned manifest](data/cleaned_manifest.json)。大文件存于Release，`git clone`只获取轻量说明、清单、示例和工具。

可直接在GitHub查看 [400条有效报告格式示例](data/example.csv)。这是按城市和时间选取的格式预览，不是代表性随机样本。

## 数据范围

共同窗口是 **2026-01-29 至 2026-03-02**，33个日历日、792个名义小时轮次。UID是源目录标识，未逐一核实为独立物理站。

| 城市 | 源目录 UID | 严格公共范围有效站点小时 | 覆盖至少90%的UID |
|---|---:|---:|---:|
| 北京 | 9,068 | 4,070,648 | 4,957 |
| 上海 | 13,265 | 6,095,332 | 7,662 |
| 深圳 | 8,484 | 3,574,573 | 4,540 |
| 重庆 | 8,117 | 4,258,375 | 5,281 |
| 合计 | 38,934 | **17,998,928** | **22,440** |

原始ZIP含3,318个CSV、31,709,085行；共同窗口中有29,672,222行。清洗版保留完整名义网格和缺测/质量掩码，**没有插值，也没有把缺测填成零占用**。读取占用率时必须同时使用 `valid`，不能仅根据数值非空判定可用。

名义小时是采集轮次，不是所有站都在整点同时观测。`capture_time`保存每行实际采集时刻；它也不是已验证的后台状态更新时间。数据表示平台报告占用，不直接测量电量、排队或现场故障。

## 重要质量限制

- 2026-02-18四城各仅有约23时的一轮快照，其余23轮缺失。
- 上海2026-03-02 17时之后整批计数归零，严格掩码已排除。
- 长时间不变不自动视为故障；百度元数据更新时间不当作充电遥测刷新时刻。
- 部分原始价格、天气和坐标字段需要单独解释，不能直接当作已验证外生特征。
- 原始镜像不作内容修改；清洗面板和精简元数据是本仓库的衍生处理。请保留原作者署名和变更说明。

## 授权与引用

原始数据与本仓库的数据衍生文件按 [CC BY 4.0](LICENSE) 提供；本仓库新写的下载/校验代码按 [MIT](LICENSE-CODE) 提供。数据授权不因工具代码使用MIT而改变。第三方来源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。本镜像不代表原作者背书。

建议首先引用原数据：

> Yu ruotao (2026). A spatiotemporal dataset of electric vehicle charging station utilization in four major Chinese cities. Figshare. https://doi.org/10.6084/m9.figshare.32917595.v1

若使用清洗版，请同时注明本仓库 `v1.0.0`、清洗日期和manifest中的校验码。机器可读引用见 [CITATION.cff](CITATION.cff)。
