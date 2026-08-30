import json
import os
import sqlite3
import tempfile
import unittest

from amac_crawler import AMACCrawler, TABLE_CONFIGS, build_parser


DETAIL_HTML = """
<html><body><table>
<tr><td class="title">基金名称：</td><td>测试基金</td></tr>
<tr><td class="title">基金类型:</td><td>创业投资基金</td></tr>
<tr><td class="title">币种：</td><td>人民币</td></tr>
<tr><td class="title">披露情况：</td><td>月报 1 条</td></tr>
<tr><td class="title">披露情况：</td><td>季报 2 条</td></tr>
</table>
<table><thead><tr><th>报告类型</th><th>应披露</th><th>未披露</th></tr></thead>
<tbody><tr><td>月报</td><td>3</td><td>0</td></tr></tbody></table>
</body></html>
"""


class FullFieldTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.crawler = AMACCrawler(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_all_structured_detail_fields(self):
        fields = self.crawler.parse_detail_fields(DETAIL_HTML)
        self.assertEqual(fields["基金名称"], "测试基金")
        self.assertEqual(fields["基金类型"], "创业投资基金")
        self.assertEqual(fields["币种"], "人民币")
        self.assertEqual(fields["披露情况"], "月报 1 条 | 季报 2 条")
        detail_table = json.loads(fields["详情表_1"])
        self.assertEqual(detail_table[0], ["报告类型", "应披露", "未披露"])
        self.assertEqual(detail_table[1], ["月报", "3", "0"])

    def test_merge_preserves_api_and_detail_collisions(self):
        merged = self.crawler.merge_full_record(
            {"fundName": "测试基金", "fundNo": "ABC1"},
            {"基金名称": "测试基金", "基金类型": "创业投资基金"},
        )
        self.assertEqual(merged["基金名称"], "测试基金")
        self.assertEqual(merged["详情_基金名称"], "测试基金")
        self.assertEqual(merged["基金类型"], "创业投资基金")

    def test_page_is_not_committed_when_any_detail_fails(self):
        config = {
            "api_url": "https://example.test/api",
            "referer": "https://example.test/index.html",
            "detail_base": "https://example.test/detail/",
            "output_file": "test.csv",
            "unique_keys": ["fundNo", "id"],
        }
        page = {
            "totalElements": 2,
            "totalPages": 1,
            "content": [
                {"id": "1", "fundNo": "A", "url": "1.html", "fundName": "一号"},
                {"id": "2", "fundNo": "B", "url": "2.html", "fundName": "二号"},
            ],
        }
        self.crawler.fetch_list_page = lambda *args, **kwargs: page

        def fake_detail(url, referer):
            if url.endswith("2.html"):
                return None
            return {"基金类型": "创业投资基金"}

        self.crawler.fetch_detail_fields = fake_detail
        with self.assertRaises(RuntimeError):
            self.crawler.crawl_table_full_fields("私募基金产品", config, max_pages=1)

        db = sqlite3.connect(os.path.join(self.tmp.name, "amac_full_fields.sqlite3"))
        count = db.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        self.assertEqual(count, 0)

    def test_successful_page_commits_only_enriched_records(self):
        config = {
            "api_url": "https://example.test/api",
            "referer": "https://example.test/index.html",
            "detail_base": "https://example.test/detail/",
            "output_file": "test.csv",
            "unique_keys": ["fundNo", "id"],
        }
        page = {
            "totalElements": 1,
            "totalPages": 1,
            "content": [
                {"id": "1", "fundNo": "A", "url": "1.html", "fundName": "一号"},
            ],
        }
        self.crawler.fetch_list_page = lambda *args, **kwargs: page
        self.crawler.fetch_detail_fields = lambda *args, **kwargs: {
            "基金类型": "创业投资基金",
            "币种": "人民币",
        }
        self.crawler.crawl_table_full_fields("私募基金产品", config, max_pages=1)

        db = sqlite3.connect(os.path.join(self.tmp.name, "amac_full_fields.sqlite3"))
        row = db.execute("SELECT merged_json, detail_complete FROM records").fetchone()
        merged = json.loads(row[0])
        self.assertEqual(row[1], 1)
        self.assertEqual(merged["基金类型"], "创业投资基金")
        self.assertEqual(merged["币种"], "人民币")

    def test_fund_account_table_is_registered_for_full_detail_capture(self):
        config = TABLE_CONFIGS["基金公司及子公司集合资管产品"]
        self.assertEqual(
            config["api_url"],
            "https://gs.amac.org.cn/amac-infodisc/api/fund/account",
        )
        self.assertEqual(
            config["detail_base"],
            "https://gs.amac.org.cn/amac-infodisc/res/fund/account/",
        )
        self.assertEqual(config["unique_keys"][0], "registerCode")

    def test_table_option_can_select_one_or_more_registered_tables(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "--table",
                "基金公司私募投资基金",
                "--table",
                "基金公司及子公司集合资管产品",
            ]
        )
        self.assertEqual(
            args.tables,
            ["基金公司私募投资基金", "基金公司及子公司集合资管产品"],
        )


if __name__ == "__main__":
    unittest.main()
