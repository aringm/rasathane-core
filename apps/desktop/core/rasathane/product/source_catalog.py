"""Original Radar category catalogue for restoring imported feed labels.

Source: apps/radar/data/feeds.yaml. Only exact known URLs (ignoring a trailing
slash) are classified; user-assigned categories are never replaced.
"""

RADAR_CATEGORIES: dict[str, str] = {
    (
        "http://export.arxiv.org/api/query?search_query=cat:cs.AI"
        "&sortBy=submittedDate&sortOrder=descending&max_results=20"
    ): "muhakeme_stack",
    (
        "http://export.arxiv.org/api/query?search_query=cat:cs.CL"
        "&sortBy=submittedDate&sortOrder=descending&max_results=20"
    ): "muhakeme_stack",
    (
        "http://export.arxiv.org/api/query?search_query=cat:cs.CV"
        "&sortBy=submittedDate&sortOrder=descending&max_results=20"
    ): "dunya_ai",
    (
        "http://export.arxiv.org/api/query?search_query=cat:cs.CY"
        "&sortBy=submittedDate&sortOrder=descending&max_results=15"
    ): "dunya_ai",
    (
        "http://export.arxiv.org/api/query?search_query=cat:cs.IR"
        "&sortBy=submittedDate&sortOrder=descending&max_results=20"
    ): "muhakeme_stack",
    (
        "http://export.arxiv.org/api/query?search_query=cat:cs.LG"
        "&sortBy=submittedDate&sortOrder=descending&max_results=20"
    ): "muhakeme_stack",
    (
        "http://export.arxiv.org/api/query?search_query=cat:cs.SE"
        "&sortBy=submittedDate&sortOrder=descending&max_results=20"
    ): "dunya_ai",
    "https://abovethelaw.com/feed": "legaltech",
    "https://artificiallawyer.com/feed": "legaltech",
    "https://blog.allenai.org/feed": "dunya_ai",
    "https://blog.lexpera.com.tr/feed": "turk_hukuku",
    "https://deepmind.google/blog/rss.xml": "dunya_ai",
    "https://github.com/01-ai/Yi/releases.atom": "china_ai_models",
    "https://github.com/AI4Bharat/IndicTrans2/releases.atom": "east_asia_ai_models",
    "https://github.com/LG-AI-EXAONE/EXAONE-3.5/releases.atom": "east_asia_ai_models",
    "https://github.com/MiniMax-AI/MiniMax-01/releases.atom": "china_ai_models",
    "https://github.com/MoonshotAI/Kimi-K2/releases.atom": "china_ai_models",
    "https://github.com/QwenLM/Qwen2.5-Coder/releases.atom": "china_ai_models",
    "https://github.com/QwenLM/Qwen2.5/releases.atom": "china_ai_models",
    "https://github.com/QwenLM/Qwen3/releases.atom": "china_ai_models",
    "https://github.com/THUDM/ChatGLM3/releases.atom": "china_ai_models",
    "https://github.com/THUDM/GLM-4/releases.atom": "china_ai_models",
    "https://github.com/Tencent-Hunyuan/HunyuanVideo/releases.atom": "china_ai_models",
    "https://github.com/aisingapore/sea-lion/releases.atom": "east_asia_ai_models",
    "https://github.com/baichuan-inc/Baichuan-7B/releases.atom": "china_ai_models",
    "https://github.com/deepseek-ai/DeepSeek-Coder-V2/releases.atom": "china_ai_models",
    "https://github.com/deepseek-ai/DeepSeek-R1/releases.atom": "china_ai_models",
    "https://github.com/deepseek-ai/DeepSeek-V3/releases.atom": "china_ai_models",
    "https://github.com/dottxt-ai/outlines/releases.atom": "model_infra",
    "https://github.com/ggml-org/llama.cpp/releases.atom": "open_weight_models",
    "https://github.com/langchain-ai/langgraph/releases.atom": "model_infra",
    "https://github.com/ml-explore/mlx/releases.atom": "model_infra",
    "https://github.com/ollama/ollama/releases.atom": "open_weight_models",
    "https://github.com/sarvamai/sarvam-1/releases.atom": "east_asia_ai_models",
    "https://github.com/sgl-project/sglang/releases.atom": "model_infra",
    "https://github.com/triton-inference-server/server/releases.atom": "model_infra",
    "https://github.com/vllm-project/vllm/releases.atom": "model_infra",
    "https://hnrss.org/frontpage": "dunya_ai",
    "https://hub.legaltechtr.com/rss.xml": "legaltech",
    "https://huggingface.co/blog/feed.xml": "dunya_ai",
    "https://hukukihaber.net/rss": "turk_hukuku",
    "https://importai.substack.com/feed": "dunya_ai",
    "https://law.stanford.edu/feed": "legaltech",
    "https://lawly.tr/blog/rss": "legaltech",
    "https://lawyerteam.pro/feed": "legaltech",
    "https://legaltalknetwork.com/feed": "legaltech",
    "https://lexchat.ai/blog/rss": "legaltech",
    "https://lilianweng.github.io/index.xml": "dunya_ai",
    "https://lmsys.org/blog/feed.xml": "open_weight_models",
    "https://magazine.sebastianraschka.com/feed": "dunya_ai",
    "https://ollama.com/blog/rss.xml": "muhakeme_stack",
    "https://openai.com/blog/rss.xml": "dunya_ai",
    "https://postgresweekly.com/rss": "muhakeme_stack",
    "https://pyfound.blogspot.com/feeds/posts/default": "muhakeme_stack",
    "https://realpython.com/atom.xml": "muhakeme_stack",
    "https://sakana.ai/rss.xml": "east_asia_ai_models",
    "https://shiftdelete.net/feed": "turkiye_ai",
    "https://simonwillison.net/atom/everything": "dunya_ai",
    "https://steipete.me/rss.xml": "dunya_ai",
    "https://stratechery.com/feed": "dunya_ai",
    "https://thegradient.pub/rss": "dunya_ai",
    "https://weaviate.io/blog/rss.xml": "muhakeme_stack",
    "https://webrazzi.com/kategori/yapay-zeka/feed": "turkiye_ai",
    "https://www.abchukuk.com/feed": "turk_hukuku",
    "https://www.alomaliye.com/feed": "turk_hukuku",
    (
        "https://www.alomaliye.com/kategori/yargi-kararlari/anayasa-mahkemesi-kararlari/feed"
    ): "turk_hukuku",
    "https://www.apilex.ai/blog/rss": "legaltech",
    "https://www.bthaber.com/feed": "turkiye_ai",
    "https://www.clio.com/blog/feed": "legaltech",
    "https://www.databricks.com/blog/feed": "dunya_ai",
    "https://www.dunyahukuk.com/feed": "turk_hukuku",
    "https://www.fullegal.com/feed": "legaltech",
    "https://www.hukukvebilisimdergisi.com/feed": "legaltech",
    "https://www.interconnects.ai/feed": "dunya_ai",
    "https://www.lawchat.com.tr/feed": "legaltech",
    "https://www.lawnext.com/feed": "legaltech",
    "https://www.lexblog.com/feed": "legaltech",
    "https://www.marketingturkiye.com.tr/feed": "turkiye_ai",
    "https://www.pinecone.io/rss": "muhakeme_stack",
    "https://www.reddit.com/r/LangChain/top.json?t=day&limit=10": "muhakeme_stack",
    "https://www.reddit.com/r/LegalTechnology/new.json?limit=15": "legaltech",
    "https://www.reddit.com/r/LocalLLaMA/top.json?t=day&limit=15": "muhakeme_stack",
    "https://www.reddit.com/r/MachineLearning/top.json?t=day&limit=15": "dunya_ai",
    "https://www.reddit.com/r/OpenAI/top.json?t=day&limit=15": "dunya_ai",
    "https://www.reddit.com/r/Python/top.json?t=day&limit=15": "muhakeme_stack",
    "https://www.reddit.com/r/law/top.json?t=day&limit=15": "legaltech",
    "https://www.reddit.com/r/programming/top.json?t=day&limit=15": "muhakeme_stack",
    "https://www.resmigazete.gov.tr": "resmi_mevzuat",
    "https://www.tebli.co/blog-feed.xml": "legaltech",
    "https://www.technologyreview.com/topic/artificial-intelligence/feed": "dunya_ai",
    "https://www.youtube.com/@3blue1brown/videos": "dunya_ai",
    "https://www.youtube.com/@AndrejKarpathy/videos": "dunya_ai",
    "https://www.youtube.com/@TwoMinutePapers/videos": "dunya_ai",
    "https://www.youtube.com/@YannicKilcher/videos": "dunya_ai",
    "https://www.youtube.com/@legaltechturkiye/videos": "legaltech",
    "https://www.youtube.com/@lexfridman/videos": "dunya_ai",
}
