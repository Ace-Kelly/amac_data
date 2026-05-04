# -*- coding: utf-8 -*-
"""
AMAC（中国证券投资基金业协会）数据爬虫
爬取5张表：
1. 私募基金产品 (pof/fund)
2. 证券公司直投基金 (aoin/product)
3. 证券公司私募投资基金 (pof/subfund)
4. 基金公司私募投资基金 (pof/pubfund)
5. 私募基金管理人 (pof/manager)
"""

import argparse
import csv
import json
import os
import random
import time
from datetime import datetime
from urllib.parse import urlparse

import requests
from lxml import etree


# ============== 配置区 ==============

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 默认输出目录
DEFAULT_OUTPUT_DIR = os.path.join(BASE_DIR, "output")

# 每页条数
PAGE_SIZE = 20

# 请求间隔（秒），防止被反爬
REQUEST_DELAY = (0.5, 1.5)  # 随机延时范围
MAX_RETRIES = 4
RETRY_BACKOFF = (1.0, 2.5)  # 失败重试的基础随机等待

# User-Agent（请替换为你自己浏览器的UA）
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# 英文字段名 → 中文表头映射（覆盖所有5张表的全部字段）
FIELD_CN_MAP = {
    # 私募基金产品
    "id": "ID",
    "fundNo": "基金编号",
    "fundName": "基金名称",
    "managerName": "管理人名称",
    "managerType": "管理类型",
    "workingState": "运作状态",
    "putOnRecordDate": "备案日期",
    "lastQuarterUpdate": "最新季度更新",
    "isDeputeManage": "是否委托管理",
    "url": "详情URL",
    "establishDate": "成立日期",
    "managerUrl": "管理人URL",
    "mandatorName": "托管人名称",
    "managersInfo": "管理人信息",
    # 证券公司直投基金
    "name": "基金名称",
    "code": "基金编号",
    "aoinName": "直投公司名称",
    "createDate": "成立日期",
    "submitDate": "提交日期",
    "fundType": "基金类型",
    "organizeType": "组织形式",
    "buyMoney": "认购金额",
    "scope": "投资范围",
    # 证券公司私募投资基金
    "productId": "产品ID",
    "productName": "产品名称",
    "productCode": "产品编号",
    "userTenantId": "用户租户ID",
    "mgrName": "管理人名称",
    "foundDate": "成立日期",
    "registeredDate": "备案日期",
    "castProduct": "投资类型",
    "orgForm": "组织形式",
    "fundStatus": "基金状态",
    "tuoGuan": "托管人",
    "trustee": "受托人",
    "delmark": "删除标记",
    # 私募基金管理人
    "artificialPersonName": "法定代表人",
    "registerNo": "登记编号",
    "managerHasProduct": "是否有产品",
    "registerDate": "登记日期",
    "registerAddress": "注册地址",
    "registerProvince": "注册省份",
    "registerCity": "注册城市",
    "regAdrAgg": "注册地区汇总",
    "officeAdrAgg": "办公地区汇总",
    "fundCount": "基金数量",
    "paidInCapital": "实缴资本",
    "subscribedCapital": "认缴资本",
    "hasSpecialTips": "是否有特别提示",
    "hasCreditTips": "是否有诚信提示",
    "regCoordinate": "注册坐标",
    "officeCoordinate": "办公坐标",
    "officeAddress": "办公地址",
    "officeProvince": "办公省份",
    "officeCity": "办公城市",
    "primaryInvestType": "主要投资类型",
    "fundTypeScaleMap": "基金类型规模",
    "memberType": "会员类型",
}

# 5张表的配置（字段从API响应动态获取，不再硬编码）
TABLE_CONFIGS = {
    "私募基金产品": {
        "api_url": "https://gs.amac.org.cn/amac-infodisc/api/pof/fund",
        "referer": "https://gs.amac.org.cn/amac-infodisc/res/pof/fund/index.html",
        "detail_base": "https://gs.amac.org.cn/amac-infodisc/res/pof/fund/",
        "output_file": "amac_私募基金产品.csv",
        "unique_keys": ["fundNo", "id"],
    },
    "证券公司直投基金": {
        "api_url": "https://gs.amac.org.cn/amac-infodisc/api/aoin/product",
        "referer": "https://gs.amac.org.cn/amac-infodisc/res/aoin/product/index.html",
        "detail_base": "https://gs.amac.org.cn/amac-infodisc/res/aoin/product/",
        "output_file": "amac_证券公司直投基金.csv",
        "unique_keys": ["code", "id"],
    },
    "证券公司私募投资基金": {
        "api_url": "https://gs.amac.org.cn/amac-infodisc/api/pof/subfund",
        "referer": "https://gs.amac.org.cn/amac-infodisc/res/pof/subfund/index.html",
        "detail_base": "https://gs.amac.org.cn/amac-infodisc/res/pof/subfund/",
        "output_file": "amac_证券公司私募投资基金.csv",
        "unique_keys": ["productCode", "productId", "id"],
    },
    "基金公司私募投资基金": {
        "api_url": "https://gs.amac.org.cn/amac-infodisc/api/pof/pubfund",
        "referer": "https://gs.amac.org.cn/amac-infodisc/res/pof/pubfund/index.html",
        "detail_base": "https://gs.amac.org.cn/amac-infodisc/res/pof/pubfund/",
        "output_file": "amac_基金公司私募投资基金.csv",
        "unique_keys": ["productCode", "productId", "id"],
    },
    "私募基金管理人": {
        "api_url": "https://gs.amac.org.cn/amac-infodisc/api/pof/manager",
        "referer": "https://gs.amac.org.cn/amac-infodisc/res/pof/manager/index.html",
        "detail_base": "https://gs.amac.org.cn/amac-infodisc/res/pof/manager/",
        "output_file": "amac_私募基金管理人.csv",
        "unique_keys": ["registerNo", "managerName", "id"],
    },
}


# ============== 爬虫核心 ==============

class AMACCrawler:
    """AMAC统一爬虫"""

    def __init__(self, output_dir=DEFAULT_OUTPUT_DIR):
        self.output_dir = os.path.abspath(output_dir)
        os.makedirs(self.output_dir, exist_ok=True)
        self.session = requests.Session()
        self._warmed_referers = set()

    def _get_headers(self, referer):
        return {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Host": "gs.amac.org.cn",
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": "https://gs.amac.org.cn",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": referer,
            "User-Agent": USER_AGENT,
        }

    def _get_pagecount_url(self, referer):
        """
        根据 referer 推导 pagecount 接口:
        /amac-infodisc/res/... -> /amac-infodisc/api/hits/pagecount
        """
        parsed = urlparse(referer)
        return f"{parsed.scheme}://{parsed.netloc}/amac-infodisc/api/hits/pagecount"

    def warmup_session(self, referer):
        """
        先访问 referer 页面并请求 pagecount，尽量贴近浏览器访问链路，减少 500/风控概率。
        同一 referer 仅预热一次。
        """
        if referer in self._warmed_referers:
            return
        try:
            # 1) 打开列表页，初始化站点 cookie
            self.session.get(referer, headers={"User-Agent": USER_AGENT}, timeout=20)
            # 2) 请求 pagecount（页面通常会发起该请求）
            pagecount_url = self._get_pagecount_url(referer)
            headers = {
                "Accept": "*/*",
                "Referer": referer,
                "X-Requested-With": "XMLHttpRequest",
                "User-Agent": USER_AGENT,
            }
            self.session.get(
                f"{pagecount_url}?random={random.random()}",
                headers=headers,
                timeout=20,
            )
            self._warmed_referers.add(referer)
        except Exception:
            # 预热失败不阻断主流程，后续靠重试兜底
            pass

    def _delay(self):
        """随机延时"""
        delay = random.uniform(*REQUEST_DELAY)
        time.sleep(delay)

    def _retry_delay(self, retry_idx):
        base = random.uniform(*RETRY_BACKOFF)
        time.sleep(base * (retry_idx + 1))

    def _get_first_value(self, item, field_spec):
        """支持单字段或候选字段名"""
        if isinstance(field_spec, (list, tuple)):
            for field in field_spec:
                val = item.get(field, "")
                if val not in ("", None):
                    return field, val
            return field_spec[0], ""
        val = item.get(field_spec, "")
        return field_spec, val

    def _normalize_date_value(self, field_name, value):
        """将毫秒时间戳转为 YYYY-MM-DD"""
        if value in ("", None):
            return value
        if isinstance(value, bool):
            return value
        if not isinstance(value, (int, float)):
            return value
        if not str(field_name).lower().endswith("date"):
            return value
        try:
            return datetime.fromtimestamp(value / 1000).strftime("%Y-%m-%d")
        except (TypeError, ValueError, OSError):
            return value

    def fetch_list_page(self, api_url, referer, page, size=PAGE_SIZE):
        """请求列表页，返回JSON数据"""
        self.warmup_session(referer)
        payload = json.dumps({})

        for retry_idx in range(MAX_RETRIES):
            rand = random.random()
            url = f"{api_url}?rand={rand}&page={page}&size={size}"
            headers = self._get_headers(referer)
            try:
                resp = self.session.post(url, data=payload, headers=headers, timeout=30)
                resp.raise_for_status()
                resp.encoding = "utf-8"
                return resp.json()
            except Exception as e:
                last_try = retry_idx == MAX_RETRIES - 1
                if last_try:
                    print(f"  [错误] 请求第{page}页失败: {e}")
                    return None
                # 出错后重做预热，再重试
                self._warmed_referers.discard(referer)
                self.warmup_session(referer)
                self._retry_delay(retry_idx)

    def fetch_detail_page(self, detail_url, referer):
        """请求详情页，返回解析后的文本"""
        headers = self._get_headers(referer)
        try:
            resp = self.session.get(detail_url, headers=headers, timeout=30)
            resp.encoding = "utf-8"
            html = etree.HTML(resp.text)
            # 尝试提取第一个表格的全部文本作为详细信息
            tables = html.xpath('//table')
            if tables:
                info = tables[0].xpath('string(.)').replace('\r\n', '').replace('\t', '').strip()
                # 压缩多余空格
                import re
                info = re.sub(r'\s+', ' ', info)
                return info
            return ""
        except Exception as e:
            print(f"  [错误] 请求详情页失败: {e}")
            return ""

    def get_total_pages(self, api_url, referer, size=PAGE_SIZE):
        """获取总页数"""
        data = self.fetch_list_page(api_url, referer, page=0, size=size)
        if data is None:
            return 0, 0
        total_elements = data.get("totalElements", 0)
        total_pages = data.get("totalPages", 0)
        print(f"  总记录数: {total_elements}, 总页数: {total_pages}")
        return total_pages, total_elements

    def _item_to_row(self, item, fields):
        """将API返回的一条记录按字段列表转为行数据，自动转换日期"""
        row = []
        for field in fields:
            val = item.get(field, "")
            val = self._normalize_date_value(field, val)
            if val is None:
                val = ""
            # list/dict 转 JSON 字符串
            if isinstance(val, (list, dict)):
                val = json.dumps(val, ensure_ascii=False)
            row.append(val)
        return row

    def crawl_table(self, table_name, config, start_page=0):
        """
        爬取一张表的全部数据，动态保存API返回的全部字段
        start_page: 断点续爬起始页（0-based），默认从头开始
        """
        print(f"\n{'='*60}")
        print(f"开始爬取: {table_name}")
        if start_page > 0:
            print(f"  [断点续爬] 从第 {start_page + 1} 页开始")
        print(f"{'='*60}")

        api_url = config["api_url"]
        referer = config["referer"]
        output_file = os.path.join(self.output_dir, config["output_file"])

        # 先请求第0页，获取总页数和字段名
        first_data = self.fetch_list_page(api_url, referer, page=0)
        if first_data is None:
            print(f"  [跳过] {table_name} 请求失败")
            return

        total_elements = first_data.get("totalElements", 0)
        total_pages = first_data.get("totalPages", 0)
        print(f"  总记录数: {total_elements}, 总页数: {total_pages}")

        if total_pages == 0:
            print(f"  [跳过] {table_name} 没有数据")
            return

        # 从第一条记录动态获取所有字段名作为CSV表头
        first_content = first_data.get("content", [])
        if not first_content:
            print(f"  [跳过] {table_name} 第一页无内容")
            return
        fields = list(first_content[0].keys())
        print(f"  字段: {fields}")

        rows = []
        failed_pages = []

        # 断点续爬：读取已有CSV数据
        if start_page > 0 and os.path.exists(output_file):
            with open(output_file, "r", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                next(reader)  # 跳过表头
                for r in reader:
                    rows.append(r)
            print(f"  已加载已有数据 {len(rows)} 条")
        else:
            # 第0页已经拿到了，先处理
            for item in first_content:
                rows.append(self._item_to_row(item, fields))

        actual_start = max(start_page, 1)
        for page in range(actual_start, total_pages):
            print(f"  第 {page+1}/{total_pages} 页...")
            data = self.fetch_list_page(api_url, referer, page)

            if data is None:
                failed_pages.append(page)
                self._delay()
                continue

            for item in data.get("content", []):
                rows.append(self._item_to_row(item, fields))

            # 每50页保存一次
            if (page + 1) % 50 == 0 or page == total_pages - 1:
                self._save_csv(output_file, fields, rows)
                print(f"  已保存 {len(rows)} 条记录到 {config['output_file']}")

            self._delay()

        # 最终保存
        self._save_csv(output_file, fields, rows)
        print(f"\n  [完成] {table_name}: 共 {len(rows)} 条记录")
        if failed_pages:
            print(f"  [警告] 失败页: {failed_pages}")

        # 重试失败的页
        if failed_pages:
            print(f"  正在重试 {len(failed_pages)} 个失败页...")
            for page in failed_pages:
                time.sleep(3)
                data = self.fetch_list_page(api_url, referer, page)
                if data is None:
                    print(f"    第{page}页重试仍然失败")
                    continue
                for item in data.get("content", []):
                    rows.append(self._item_to_row(item, fields))
            self._save_csv(output_file, fields, rows)
            print(f"  重试完成，最终共 {len(rows)} 条记录")

    def _translate_header(self, fields):
        """将英文字段名转为中文表头"""
        return [FIELD_CN_MAP.get(f, f) for f in fields]

    def _normalize_key(self, val):
        if val in ("", None):
            return ""
        return str(val).strip()

    def _extract_key_from_item(self, item, key_fields):
        for k in key_fields:
            v = self._normalize_key(item.get(k, ""))
            if v:
                return v
        return ""

    def _extract_key_from_row(self, row, fields, key_fields):
        for k in key_fields:
            if k not in fields:
                continue
            idx = fields.index(k)
            if idx >= len(row):
                continue
            v = self._normalize_key(row[idx])
            if v:
                return v
        return ""

    def repair_table(self, table_name, config):
        """
        自动补漏模式：
        1) 读取现有CSV
        2) 基于唯一键去重
        3) 全页扫描接口，仅补缺失记录
        """
        print(f"\n{'='*60}")
        print(f"自动补漏: {table_name}")
        print(f"{'='*60}")

        api_url = config["api_url"]
        referer = config["referer"]
        output_file = os.path.join(self.output_dir, config["output_file"])
        key_fields = config.get("unique_keys", ["id"])

        first_data = self.fetch_list_page(api_url, referer, page=0)
        if first_data is None:
            print(f"  [跳过] {table_name} 请求失败")
            return

        total_elements = first_data.get("totalElements", 0)
        total_pages = first_data.get("totalPages", 0)
        print(f"  接口总记录数: {total_elements}, 总页数: {total_pages}")
        if total_pages == 0:
            print(f"  [跳过] {table_name} 没有数据")
            return

        first_content = first_data.get("content", [])
        if not first_content:
            print(f"  [跳过] {table_name} 第一页无内容")
            return
        fields = list(first_content[0].keys())

        existing_rows = []
        existing_keys = set()

        if os.path.exists(output_file):
            with open(output_file, "r", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                next(reader, None)  # 跳过表头
                for row in reader:
                    key = self._extract_key_from_row(row, fields, key_fields)
                    if key and key in existing_keys:
                        continue
                    if key:
                        existing_keys.add(key)
                    existing_rows.append(row)
        else:
            print("  [提示] 未找到历史CSV，将执行全量抓取并保存。")

        print(f"  本地已有记录(去重后): {len(existing_rows)}")

        added_rows = []
        failed_pages = []

        for page in range(total_pages):
            print(f"  扫描第 {page+1}/{total_pages} 页...")
            data = self.fetch_list_page(api_url, referer, page)
            if data is None:
                failed_pages.append(page)
                self._delay()
                continue

            for item in data.get("content", []):
                key = self._extract_key_from_item(item, key_fields)
                if key and key in existing_keys:
                    continue
                row = self._item_to_row(item, fields)
                added_rows.append(row)
                if key:
                    existing_keys.add(key)

            self._delay()

        if failed_pages:
            print(f"  重试失败页: {failed_pages}")
            for page in failed_pages:
                time.sleep(3)
                data = self.fetch_list_page(api_url, referer, page)
                if data is None:
                    print(f"    第{page}页重试仍失败")
                    continue
                for item in data.get("content", []):
                    key = self._extract_key_from_item(item, key_fields)
                    if key and key in existing_keys:
                        continue
                    row = self._item_to_row(item, fields)
                    added_rows.append(row)
                    if key:
                        existing_keys.add(key)

        final_rows = existing_rows + added_rows
        self._save_csv(output_file, fields, final_rows)

        print(f"  新增补漏记录: {len(added_rows)}")
        print(f"  补漏后总记录: {len(final_rows)}")
        if len(final_rows) < total_elements:
            print(f"  [提示] 仍少于接口总记录数，可能仍有页抓取失败或接口数据在变动。")
        else:
            print("  [完成] 补漏完成。")

    def _save_csv(self, filepath, fields, rows):
        """保存数据到CSV，表头使用中文，分批写入避免OSError"""
        BATCH = 5000
        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(self._translate_header(fields))
            for i in range(0, len(rows), BATCH):
                writer.writerows(rows[i:i + BATCH])

    def smoke_test_table(self, table_name, config):
        """请求单张表第一页，验证接口连通性与字段解析是否正常"""
        print(f"\n{'='*60}")
        print(f"联通性测试: {table_name}")
        print(f"{'='*60}")

        data = self.fetch_list_page(config["api_url"], config["referer"], page=0)
        if data is None:
            print("  [失败] 接口请求失败")
            return False

        total_elements = data.get("totalElements", 0)
        total_pages = data.get("totalPages", 0)
        content = data.get("content", [])

        print(f"  总记录数: {total_elements}")
        print(f"  总页数: {total_pages}")
        print(f"  当前页记录数: {len(content)}")

        if not content:
            print("  [失败] 第一页无内容，无法验证字段结构")
            return False

        first_item = content[0]
        fields = list(first_item.keys())
        print(f"  字段数: {len(fields)}")
        print(f"  字段列表: {fields}")

        preview_pairs = []
        for key in fields[:5]:
            preview_pairs.append(f"{key}={self._normalize_date_value(key, first_item.get(key, ''))}")
        print(f"  样例记录前5项: {'; '.join(preview_pairs)}")
        print("  [成功] 接口可访问，字段解析正常")
        return True


def build_parser():
    parser = argparse.ArgumentParser(
        description="AMAC（中国证券投资基金业协会）公开信息爬虫"
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="CSV 输出目录，默认写入脚本同级 output 文件夹",
    )
    parser.add_argument(
        "--list-tables",
        action="store_true",
        help="列出支持抓取的表名后退出",
    )
    parser.add_argument(
        "--resume",
        nargs=2,
        metavar=("TABLE", "PAGE"),
        help="从指定表的指定页（0-based）继续抓取",
    )
    parser.add_argument(
        "--repair",
        metavar="TABLE",
        help="对指定表按唯一键补漏和去重",
    )
    parser.add_argument(
        "--repair-all",
        action="store_true",
        help="对全部表执行补漏",
    )
    parser.add_argument(
        "--smoke-test",
        metavar="TABLE",
        help="只请求指定表第一页，用于验证接口是否能正常访问",
    )
    return parser


# ============== 主程序 ==============

def main():
    """
    运行爬虫。

    使用方式:
        1. 直接运行: python amac_crawler.py
           -> 默认爬取全部5张表
        2. 断点续爬: python amac_crawler.py --resume 私募基金产品 8750
           -> 从第8750页继续爬取指定表，然后继续后续表
        3. 自动补漏: python amac_crawler.py --repair 私募基金产品
           -> 读取现有CSV并按唯一键自动补漏、去重
        4. 全部补漏: python amac_crawler.py --repair-all
           -> 对5张表按顺序执行自动补漏
    """
    parser = build_parser()
    args = parser.parse_args()

    # 全部表（按顺序）
    all_tables = [
        "私募基金产品",
        "证券公司直投基金",
        "证券公司私募投资基金",
        "基金公司私募投资基金",
        "私募基金管理人",
    ]

    crawler = AMACCrawler(output_dir=args.output_dir)

    if args.list_tables:
        print("支持的表名:")
        for table_name in all_tables:
            print(f"- {table_name}")
        return 0

    resume_table = None
    resume_page = 0
    repair_table = args.repair
    repair_all = args.repair_all
    smoke_test_table = args.smoke_test

    if args.resume is not None:
        resume_table = args.resume[0]
        resume_page = int(args.resume[1])

    print("=" * 60)
    print("AMAC 基金业协会数据爬虫")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    if smoke_test_table is not None:
        if smoke_test_table not in TABLE_CONFIGS:
            print(f"[错误] 不支持的表名: {smoke_test_table}")
            print(f"可选表名: {list(TABLE_CONFIGS.keys())}")
            return 1
        success = crawler.smoke_test_table(smoke_test_table, TABLE_CONFIGS[smoke_test_table])
        print(f"\n{'='*60}")
        print(f"测试结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"输出目录: {crawler.output_dir}")
        print(f"{'='*60}")
        return 0 if success else 1

    if repair_table is not None:
        if repair_table not in TABLE_CONFIGS:
            print(f"[错误] 不支持的表名: {repair_table}")
            print(f"可选表名: {list(TABLE_CONFIGS.keys())}")
            return 1
        crawler.repair_table(repair_table, TABLE_CONFIGS[repair_table])
        print(f"\n{'='*60}")
        print(f"补漏完成! 结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"输出目录: {crawler.output_dir}")
        print(f"{'='*60}")
        return 0

    if repair_all:
        for table_name in all_tables:
            if table_name not in TABLE_CONFIGS:
                continue
            crawler.repair_table(table_name, TABLE_CONFIGS[table_name])
        print(f"\n{'='*60}")
        print(f"全部补漏完成! 结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"输出目录: {crawler.output_dir}")
        print(f"{'='*60}")
        return 0

    started = resume_table is None
    for table_name in all_tables:
        if table_name not in TABLE_CONFIGS:
            continue
        if not started:
            if table_name == resume_table:
                started = True
                config = TABLE_CONFIGS[table_name]
                crawler.crawl_table(table_name, config, start_page=resume_page)
                continue
            else:
                print(f"  [跳过] {table_name}（断点续爬，跳到 {resume_table}）")
                continue
        config = TABLE_CONFIGS[table_name]
        crawler.crawl_table(table_name, config)

    print(f"\n{'='*60}")
    print(f"全部完成! 结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"输出目录: {crawler.output_dir}")
    print(f"{'='*60}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
