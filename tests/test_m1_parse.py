import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.parse import join_roles, parse_permission, role_labels


class ParsePermissionTest(unittest.TestCase):
    def test_site_group_grant_inherited(self):
        entry = {
            "id": "VHJhZGUgU2VjcmV0IE93bmVycw",
            "roles": ["owner"],
            "grantedToV2": {
                "siteGroup": {"displayName": "Trade Secret Owners", "id": "3",
                              "loginName": "Trade Secret Owners"},
                "sharePointGroup": {"id": "NzNi...", "title": "Trade Secret Owners",
                                    "principalId": "3"},
            },
            "inheritedFrom": {"driveId": "b!x", "id": "root"},
        }
        parsed = parse_permission(entry)
        self.assertTrue(parsed["inherited"])
        self.assertEqual(parsed["roles"], "owner")
        self.assertEqual(parsed["roles_label"], "Full Control")
        self.assertEqual(parsed["principal"]["key"], "spgroup:3")
        self.assertEqual(parsed["principal"]["type"], "spgroup")
        self.assertIsNone(parsed["link"])

    def test_user_grant_direct(self):
        entry = {
            "id": "p2",
            "roles": ["write", "read"],
            "grantedToV2": {"user": {"id": "u1", "email": "Reader@Danfoss.com",
                                      "displayName": "Reader"}},
        }
        parsed = parse_permission(entry)
        self.assertFalse(parsed["inherited"])
        self.assertEqual(parsed["principal"]["key"], "user:reader@danfoss.com")
        self.assertEqual(parsed["roles"], "write;read")

    def test_sharing_link_with_recipients(self):
        entry = {
            "id": "p5",
            "roles": ["read"],
            "link": {"type": "edit", "scope": "users", "webUrl": "https://x",
                     "webHtml": "<a>", "preventsDownload": True},
            "grantedToIdentitiesV2": [
                {"user": {"email": "a@x.com", "displayName": "A"}},
                {"user": {"email": "b@x.com", "displayName": "B"}},
            ],
            "grantedBy": {"user": {"id": "o1", "email": "owner@x.com",
                                    "displayName": "Owner"}},
        }
        parsed = parse_permission(entry)
        self.assertIsNotNone(parsed["link"])
        link = parsed["link"]
        self.assertEqual(link["link_type"], "edit")
        self.assertEqual(link["link_scope"], "users")
        self.assertEqual(link["recipient_count"], 2)
        self.assertEqual(link["owner"]["key"], "user:owner@x.com")
        self.assertTrue(link["prevents_download"])
        self.assertIsNone(parsed["principal"])

    def test_role_join_and_labels(self):
        self.assertEqual(join_roles(["owner", "read"]), "owner;read")
        self.assertEqual(role_labels(["owner", "read"]), "Full Control;Read")


if __name__ == "__main__":
    unittest.main()
