# -*- coding: utf-8 -*-
"""
AMAC（中国证券投资基金业协会）数据爬虫
按数据量由小到大爬取5张表：
1. 基金公司私募投资基金 (pof/pubfund)
2. 证券公司直投基金 (aoin/product)
3. 证券公司私募投资基金 (pof/subfund)
4. 私募基金管理人 (pof/manager)
5. 私募基金产品 (pof/fund)
"""

import argparse
import csv
import json
import os
import random
import re
import sqlite3
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
        self.database_path = os.path.join(
            self.output_dir, "amac_full_fields.sqlite3"
        )
        self.session = requests.Session()
        self._warmed_referers = set()

    def _open_full_fields_db(self):
        """打开断点数据库，并确保完整记录与页状态表存在。"""
        db = sqlite3.connect(self.database_path)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS records (
                table_name TEXT NOT NULL,
                record_key TEXT NOT NULL,
                source_page INTEGER NOT NULL,
                detail_url TEXT NOT NULL,
                list_json TEXT NOT NULL,
                detail_json TEXT NOT NULL,
                merged_json TEXT NOT NULL,
                detail_complete INTEGER NOT NULL CHECK(detail_complete = 1),
                captured_at TEXT NOT NULL,
                PRIMARY KEY (table_name, record_key)
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS page_state (
                table_name TEXT NOT NULL,
                page_number INTEGER NOT NULL,
                record_count INTEGER NOT NULL,
                completed_at TEXT NOT NULL,
                PRIMARY KEY (table_name, page_number)
            )
            """
        )
        db.commit()
        return db

    @staticmethod
    def _clean_text(value):
        return re.sub(r"\s+", " ", value or "").strip()

    def parse_detail_fields(self, html_text):
        """动态提取详情页全部结构化标题/值，不写死字段名。"""
        root = etree.HTML(html_text)
        if root is None:
            return {}
        result = {}
        for title_node in root.xpath('//td[contains(concat(" ", normalize-space(@class), " "), " title ")]'):
            label = self._clean_text(title_node.xpath("string(.)"))
            label = re.sub(r"[：:]\s*$", "", label)
            values = title_node.xpath("following-sibling::td[1]")
            if not label or not values:
                continue
            value = self._clean_text(values[0].xpath("string(.)"))
            if label in result and value and value not in result[label].split(" | "):
                result[label] = f"{result[label]} | {value}" if result[label] else value
            elif label not in result:
                result[label] = value
        detail_table_number = 0
        for table in root.xpath("//table"):
            if table.xpath('.//td[contains(concat(" ", normalize-space(@class), " "), " title ")]'):
                continue
            rows = []
            for tr in table.xpath(".//tr"):
                cells = [
                    self._clean_text(cell.xpath("string(.)"))
                    for cell in tr.xpath("./th|./td")
                ]
                if any(cells):
                    rows.append(cells)
            if rows:
                detail_table_number += 1
                result[f"详情表_{detail_table_number}"] = json.dumps(
                    rows, ensure_ascii=False
                )
        return result

    def fetch_detail_fields(self, detail_url, referer):
        """带重试读取详情；失败返回 None，禁止把不完整记录写入数据库。"""
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": referer,
            "User-Agent": USER_AGENT,
        }
        for retry_idx in range(MAX_RETRIES):
            try:
                resp = self.session.get(detail_url, headers=headers, timeout=30)
                resp.raise_for_status()
                resp.encoding = "utf-8"
                fields = self.parse_detail_fields(resp.text)
                if not fields:
                    raise ValueError("详情页未解析出结构化字段")
                return fields
            except Exception as exc:
                if retry_idx == MAX_RETRIES - 1:
                    print(f"  [错误] 详情页失败 {detail_url}: {exc}")
                    return None
                self._retry_delay(retry_idx)

    def _build_detail_url(self, item, config):
        raw = item.get("url") or item.get("productId") or item.get("id")
        if raw in (None, ""):
            return ""
        raw = str(raw)
        if raw.startswith(("http://", "https://")):
            return raw
        if not raw.endswith(".html"):
            raw += ".html"
        return config["detail_base"] + raw

    def merge_full_record(self, list_item, detail_fields):
        """保留 API 与详情页全部字段；重名详情字段加来源前缀。"""
        merged = {}
        for raw_name, value in list_item.items():
            header = FIELD_CN_MAP.get(raw_name, raw_name)
            if header in merged:
                header = f"列表_{raw_name}"
            value = self._normalize_date_value(raw_name, value)
            if isinstance(value, (list, dict)):
                value = json.dumps(value, ensure_ascii=False)
            merged[header] = "" if value is None else value
        for label, value in detail_fields.items():
            header = label if label not in merged else f"详情_{label}"
            merged[header] = value
        return merged

    def _export_full_fields_csv(self, db, table_name, output_file):
        """从完整记录库导出字段并集；数据库才是断点与完整性真源。"""
        fields = []
        seen = set()
        query = (
            "SELECT merged_json FROM records WHERE table_name=? "
            "ORDER BY source_page, record_key"
        )
        record_count = 0
        for row in db.execute(query, (table_name,)):
            record = json.loads(row[0])
            record_count += 1
            for field in record:
                if field not in seen:
                    seen.add(field)
                    fields.append(field)
        if record_count == 0:
            return
        tmp_file = output_file + ".tmp"
        with open(tmp_file, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in db.execute(query, (table_name,)):
                writer.writerow(json.loads(row[0]))
        os.replace(tmp_file, output_file)

    def crawl_table_full_fields(self, table_name, config, start_page=0, max_pages=None):
        """列表与详情同轮合并；整页全部成功后才以单事务落库。"""
        print(f"\n{'=' * 60}\n全字段抓取: {table_name}\n{'=' * 60}")
        first_data = self.fetch_list_page(config["api_url"], config["referer"], 0)
        if first_data is None:
            raise RuntimeError(f"{table_name} 列表接口请求失败")
        total_pages = first_data.get("totalPages", 0)
        total_elements = first_data.get("totalElements", 0)
        stop_page = total_pages
        if max_pages is not None:
            stop_page = min(stop_page, start_page + max_pages)
        print(f"  总记录数: {total_elements}, 总页数: {total_pages}")

        db = self._open_full_fields_db()
        output_file = os.path.join(self.output_dir, config["output_file"])
        try:
            for page in range(start_page, stop_page):
                done = db.execute(
                    "SELECT 1 FROM page_state WHERE table_name=? AND page_number=?",
                    (table_name, page),
                ).fetchone()
                if done:
                    print(f"  第 {page + 1}/{total_pages} 页已完整入库，跳过")
                    continue
                data = first_data if page == 0 else self.fetch_list_page(
                    config["api_url"], config["referer"], page
                )
                if data is None:
                    raise RuntimeError(f"{table_name} 第 {page + 1} 页列表失败")
                pending = []
                for item in data.get("content", []):
                    detail_url = self._build_detail_url(item, config)
                    if not detail_url:
                        raise RuntimeError(
                            f"{table_name} 第 {page + 1} 页记录缺少详情标识"
                        )
                    detail = self.fetch_detail_fields(detail_url, config["referer"])
                    if detail is None:
                        raise RuntimeError(
                            f"{table_name} 第 {page + 1} 页存在详情失败，整页未入库"
                        )
                    record_key = self._extract_key_from_item(
                        item, config.get("unique_keys", ["id"])
                    )
                    if not record_key:
                        raise RuntimeError(
                            f"{table_name} 第 {page + 1} 页记录缺少唯一键"
                        )
                    merged = self.merge_full_record(item, detail)
                    pending.append(
                        (
                            table_name,
                            record_key,
                            page,
                            detail_url,
                            json.dumps(item, ensure_ascii=False),
                            json.dumps(detail, ensure_ascii=False),
                            json.dumps(merged, ensure_ascii=False),
                            1,
                            datetime.now().isoformat(timespec="seconds"),
                        )
                    )
                    self._delay()
                with db:
                    db.executemany(
                        """
                        INSERT OR REPLACE INTO records
                        (table_name, record_key, source_page, detail_url, list_json,
                         detail_json, merged_json, detail_complete, captured_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        pending,
                    )
                    db.execute(
                        """
                        INSERT OR REPLACE INTO page_state
                        (table_name, page_number, record_count, completed_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            table_name,
                            page,
                            len(pending),
                            datetime.now().isoformat(timespec="seconds"),
                        ),
                    )
                print(f"  第 {page + 1}/{total_pages} 页完整入库: {len(pending)} 条")
                if (page + 1) % 50 == 0 or page == stop_page - 1:
                    self._export_full_fields_csv(db, table_name, output_file)
            self._export_full_fields_csv(db, table_name, output_file)
        finally:
            db.close()

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
    # 小表优先，先尽快形成可完整验收的成果；最大表放在最后。
    all_tables = [
        "基金公司私募投资基金",
        "证券公司直投基金",
        "证券公司私募投资基金",
        "私募基金管理人",
        "私募基金产品",
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
        crawler.crawl_table_full_fields(repair_table, TABLE_CONFIGS[repair_table])
        print(f"\n{'='*60}")
        print(f"补漏完成! 结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"输出目录: {crawler.output_dir}")
        print(f"{'='*60}")
        return 0

    if repair_all:
        for table_name in all_tables:
            if table_name not in TABLE_CONFIGS:
                continue
            crawler.crawl_table_full_fields(table_name, TABLE_CONFIGS[table_name])
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
                crawler.crawl_table_full_fields(
                    table_name, config, start_page=resume_page
                )
                continue
            else:
                print(f"  [跳过] {table_name}（断点续爬，跳到 {resume_table}）")
                continue
        config = TABLE_CONFIGS[table_name]
        crawler.crawl_table_full_fields(table_name, config)

    print(f"\n{'='*60}")
    print(f"全部完成! 结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"输出目录: {crawler.output_dir}")
    print(f"{'='*60}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
