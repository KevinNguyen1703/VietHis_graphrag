from nano_graphrag import GraphRAG
from chunking import chunking_by_markers
from history_graphrag import MilvusLiteStorge
import os

def neo4j_config():
    return {
        "neo4j_url": os.environ.get("NEO4J_URL", "bolt://localhost:7687"),
        "neo4j_auth": (
            os.environ.get("NEO4J_USER", "neo4j"),
            os.environ.get("NEO4J_PASSWORD", "Gumiho123"),
        ),
    }


def insert(data):
    graphdb_config=neo4j_config()
    rag = GraphRAG(
        working_dir="./nano_graphrag_history_entity_alignment_3",
        enable_llm_cache=True,
        chunk_func=chunking_by_markers,
        vector_db_storage_cls=MilvusLiteStorge,
        addon_params = graphdb_config,
        best_model_max_async=8,
        cheap_model_max_async=8
    )
    rag.insert(data)

if __name__ == "__main__":
    folder_path = "/Users/gumiho/Gumiho/project/AI-project/LocalGraphRAG/HistoryGraphRAG/dataset/text-extracted/addition_knowledge"
    file_contents = []
    raw_text = ""
    with open("/Users/gumiho/Gumiho/project/AI-project/LocalGraphRAG/HistoryGraphRAG/dataset/text-extracted/lichsu12/full.txt", 'r', encoding='utf-8') as file:
        text = file.read()
        file_contents.append(text)
        raw_text += text
    # for filename in os.listdir(folder_path):
    #     file_path = os.path.join(folder_path, filename)
    #     if os.path.isfile(file_path):  # Check if it's a file (not a directory)
    #         with open(file_path, 'r', encoding='utf-8') as file:
    #             text = file.read()
    #             file_contents.append(text)
    #             raw_text+=f"\nI. {text}"

    insert(raw_text)