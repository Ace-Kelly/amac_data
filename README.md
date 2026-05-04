# AMAC 基金业协会公示数据爬虫

这是一个用于抓取中国证券投资基金业协会（AMAC）公开信息的 Python 爬虫，面向 CVC 研究里的基金识别与交叉验证场景。

当前脚本支持抓取 5 张公开表：

- 私募基金产品
- 证券公司直投基金
- 证券公司私募投资基金
- 基金公司私募投资基金
- 私募基金管理人

## 数据来源

- 网站：<https://gs.amac.org.cn>
- 类型：AMAC 信息公示系统公开数据
- 方式：模拟浏览器请求公开接口，按页抓取并导出为 CSV

## 环境要求

- Python 3.10+
- Windows / macOS / Linux 均可

安装依赖：

```bash
pip install -r requirements.txt
```

## 快速开始

1. 列出支持的表名：

```bash
python amac_crawler.py --list-tables
```

2. 先做联通性测试（只请求第一页，不落盘）：

```bash
python amac_crawler.py --smoke-test "私募基金管理人"
```

3. 抓取全部 5 张表：

```bash
python amac_crawler.py
```

4. 指定输出目录：

```bash
python amac_crawler.py --output-dir ./output
```

## 常用命令

断点续爬：

```bash
python amac_crawler.py --resume "私募基金产品" 8750
```

补漏单张表：

```bash
python amac_crawler.py --repair "私募基金产品"
```

补漏全部表：

```bash
python amac_crawler.py --repair-all
```

## 输出说明

- 默认输出目录为脚本同级的 `output/`
- CSV 编码为 `utf-8-sig`
- 表头会自动转换为中文字段名

典型输出文件：

- `amac_私募基金产品.csv`
- `amac_私募基金管理人.csv`
- `amac_证券公司私募投资基金.csv`
- `amac_证券公司直投基金.csv`
- `amac_基金公司私募投资基金.csv`

## 仓库说明

本仓库只保留代码和文档，不提交已抓取的 CSV 数据文件。若你本地已经有历史数据，请放在 `output/` 或其他自定义目录中，并保持忽略规则开启。

## 开源协议

本项目代码采用 MIT License 开源。协议仅适用于本仓库中的代码和文档，不包含用户本地抓取、整理或另行保存的数据文件。

## 注意事项

- AMAC 接口存在风控和偶发失败，脚本内已加入随机延时、预热请求和自动重试。
- 若接口字段顺序或字段名发生变化，脚本会按接口返回结果动态生成表头。
- 建议不要把请求频率调得过高，避免触发访问限制。
