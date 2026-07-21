from typing import Final
from uuid import UUID


DEMO_WORKSPACE_ID: Final = UUID("00000000-0000-7000-8000-000000000001")

DEMO_WORKSPACE: Final = {
    "id": str(DEMO_WORKSPACE_ID),
    "name": "内容运营示例工作区",
    "label": "示例数据",
    "synthetic": True,
    "accounts": [
        {
            "id": "douyin-demo",
            "name": "城市穿搭研究所",
            "platform": "douyin",
            "synthetic": True,
            "posts": [
                {
                    "id": "douyin-post-1",
                    "title": "一件衬衫，通勤和周末两种穿法",
                    "published_at": "2026-07-08T12:00:00+08:00",
                    "metrics": {"views": 18640, "likes": 1327, "comments": 96},
                    "synthetic": True,
                },
                {
                    "id": "douyin-post-2",
                    "title": "小个子夏天显高的三个细节",
                    "published_at": "2026-07-12T18:30:00+08:00",
                    "metrics": {"views": 32410, "likes": 2681, "comments": 173},
                    "synthetic": True,
                },
            ],
        },
        {
            "id": "xiaohongshu-demo",
            "name": "通勤灵感簿",
            "platform": "xiaohongshu",
            "synthetic": True,
            "posts": [
                {
                    "id": "xiaohongshu-post-1",
                    "title": "把基础款穿出松弛感，我只改了这三处",
                    "published_at": "2026-07-09T20:00:00+08:00",
                    "metrics": {"views": 9630, "likes": 1188, "comments": 84},
                    "synthetic": True,
                },
                {
                    "id": "xiaohongshu-post-2",
                    "title": "上班不想费脑：一周五套清爽配色",
                    "published_at": "2026-07-14T19:15:00+08:00",
                    "metrics": {"views": 14120, "likes": 1764, "comments": 121},
                    "synthetic": True,
                },
            ],
        },
    ],
}
