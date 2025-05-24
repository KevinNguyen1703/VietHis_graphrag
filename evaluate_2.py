from nano_graphrag import GraphRAG, QueryParam
import pandas as pd
from history_graphrag import MilvusLiteStorge, ollama_model_if_cache
from index_graphrag import neo4j_config

VALIDATION_PROMPT="""
Bạn là một trợ lý AI chuyên gia về trả lời câu hỏi trắc nghiệm. Hãy đọc kỹ câu hỏi sau và chỉ trả lời bằng một ký tự đại diện cho đáp án đúng (A, B, C, D). Không giải thích, không đưa thêm thông tin, chỉ trả về một ký tự duy nhất:
Câu hỏi:
    {question}
Định dạng đầu ra:
- Chỉ trả về một ký tự (A, B, C hoặc D)
"""
MODEL = "llama3.1"

def query(working_dir, return_context, model=None):
    if model == 'gpt':
        rag = GraphRAG(
            working_dir=working_dir,
            enable_llm_cache=True,
            vector_db_storage_cls=MilvusLiteStorge
        )
    else:
        rag = GraphRAG(
            working_dir=working_dir,
            enable_llm_cache=True,
            vector_db_storage_cls=MilvusLiteStorge,
            best_model_func=ollama_model_if_cache,
            cheap_model_func=ollama_model_if_cache
        )
    print(rag.query("""
Nhận xét nào dưới đây về phong trào cách mạng 1930-1931 ở Việt Nam là không đúng?
A.	Đây là phong trào cách mạng có hình thức đấu tranh phong phú, quyết liệt.
B.	Đây là phong trào cách mạng triệt để, không ảo tưởng vào kẻ thù của dân tộc. 
C.	Đây là phong trào diễn ra trên quy mô rộng lớn và mang tính thống nhất cao.
D. Đây là phong trào cách mạng mang đậm tính dân tộc hơn tính giai cấp.
""", param=QueryParam(mode="local",only_need_context=return_context)))


def process_questions(input_file, output_file, working_dir, mode="local", model=None, debug=False):
    df = pd.read_excel(input_file)

    llm_answers = []
    validations = []
    correct_count = 0
    total_questions = len(df)
    if model == 'gpt':
        rag = GraphRAG(
            working_dir=working_dir,
            enable_llm_cache=True,
            vector_db_storage_cls=MilvusLiteStorge,
            addon_params = neo4j_config()
        )
    else:
        rag = GraphRAG(
            working_dir=working_dir,
            enable_llm_cache=True,
            vector_db_storage_cls=MilvusLiteStorge,
            best_model_func=ollama_model_if_cache,
            cheap_model_func=ollama_model_if_cache
        )
    for index, row in df.iterrows():
        query = row["Question"]
        correct_answer = row["Answer"].strip()

        # Graph RAG flow
        response = rag.query(query, param=QueryParam(mode=mode,only_need_context=False))
        llm_answers.append(response)

        if debug:
            full_query=rag.query(query, param=QueryParam(mode=mode,only_need_context=True))
            print(f"Question {index+1} \n - Query: \n {full_query}\n ---> Answer: {response} \n-----------------------\n")
        if response == correct_answer:
            validation = "✅"
            print(f"Question {index+1}: ✅\n")
            correct_count += 1
        else:
            print(f"Question {index+1}: ❌\n")
            validation = "❌"

        validations.append(validation)

    df["LLM Answer"] = llm_answers
    df["Validation"] = validations
    print(f"Kết quả đã được lưu vào {output_file}")
    print(f"Số câu trả lời đúng: {correct_count}/{total_questions}")
    df.to_excel(output_file, index=False)


if __name__ == "__main__":
    query(working_dir='./nano_graphrag_history_entity_alignment_3', model='gpt', return_context=True)

    # process_questions("/Users/gumiho/Gumiho/project/AI-project/LocalGraphRAG/HistoryGraphRAG/evaluation/2017_2018.xlsx",
    #                   "/Users/gumiho/Gumiho/project/AI-project/LocalGraphRAG/HistoryGraphRAG/evaluation/validation-2017-2018/graphRAG_entity_alignment_rerank_filter.xlsx", working_dir='./nano_graphrag_history_entity_alignment_3', model='gpt', debug=False)
