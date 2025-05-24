import re
import json
import asyncio
import tiktoken
from typing import Union
from collections import Counter, defaultdict
from ._splitter import SeparatorSplitter
from ._utils import (
    logger,
    clean_str,
    compute_mdhash_id,
    decode_tokens_by_tiktoken,
    encode_string_by_tiktoken,
    is_float_regex,
    list_of_list_to_csv,
    pack_user_ass_to_openai_messages,
    split_string_by_multi_markers,
    truncate_list_by_token_size,
)
from .base import (
    BaseGraphStorage,
    BaseKVStorage,
    BaseVectorStorage,
    SingleCommunitySchema,
    CommunitySchema,
    TextChunkSchema,
    QueryParam,
)
from .prompt import GRAPH_FIELD_SEP, PROMPTS
import psycopg2
from datetime import datetime
from dateutil.relativedelta import relativedelta

def chunking_by_token_size(
    tokens_list: list[list[int]],
    doc_keys,
    tiktoken_model,
    overlap_token_size=128,
    max_token_size=1024,
):

    results = []
    for index, tokens in enumerate(tokens_list):
        chunk_token = []
        lengths = []
        for start in range(0, len(tokens), max_token_size - overlap_token_size):

            chunk_token.append(tokens[start : start + max_token_size])
            lengths.append(min(max_token_size, len(tokens) - start))

        # here somehow tricky, since the whole chunk tokens is list[list[list[int]]] for corpus(doc(chunk)),so it can't be decode entirely
        chunk_token = tiktoken_model.decode_batch(chunk_token)
        for i, chunk in enumerate(chunk_token):

            results.append(
                {
                    "tokens": lengths[i],
                    "content": chunk.strip(),
                    "chunk_order_index": i,
                    "full_doc_id": doc_keys[index],
                }
            )

    return results


def chunking_by_seperators(
    tokens_list: list[list[int]],
    doc_keys,
    tiktoken_model,
    overlap_token_size=128,
    max_token_size=1024,
):

    splitter = SeparatorSplitter(
        separators=[
            tiktoken_model.encode(s) for s in PROMPTS["default_text_separator"]
        ],
        chunk_size=max_token_size,
        chunk_overlap=overlap_token_size,
    )
    results = []
    for index, tokens in enumerate(tokens_list):
        chunk_token = splitter.split_tokens(tokens)
        lengths = [len(c) for c in chunk_token]

        # here somehow tricky, since the whole chunk tokens is list[list[list[int]]] for corpus(doc(chunk)),so it can't be decode entirely
        chunk_token = tiktoken_model.decode_batch(chunk_token)
        for i, chunk in enumerate(chunk_token):

            results.append(
                {
                    "tokens": lengths[i],
                    "content": chunk.strip(),
                    "chunk_order_index": i,
                    "full_doc_id": doc_keys[index],
                }
            )

    return results


def get_chunks(new_docs, chunk_func=chunking_by_token_size, **chunk_func_params):
    inserting_chunks = {}

    new_docs_list = list(new_docs.items())
    docs = [new_doc[1]["content"] for new_doc in new_docs_list]
    doc_keys = [new_doc[0] for new_doc in new_docs_list]

    ENCODER = tiktoken.encoding_for_model("gpt-4o")
    tokens = ENCODER.encode_batch(docs, num_threads=16)
    chunks = chunk_func(
        tokens, doc_keys=doc_keys, tiktoken_model=ENCODER, **chunk_func_params
    )

    for chunk in chunks:
        inserting_chunks.update(
            {compute_mdhash_id(chunk["content"], prefix="chunk-"): chunk}
        )

    return inserting_chunks


async def _handle_entity_relation_summary(
    entity_or_relation_name: str,
    description: str,
    global_config: dict,
) -> str:
    use_llm_func: callable = global_config["cheap_model_func"]
    llm_max_tokens = global_config["cheap_model_max_token_size"]
    tiktoken_model_name = global_config["tiktoken_model_name"]
    summary_max_tokens = global_config["entity_summary_to_max_tokens"]

    tokens = encode_string_by_tiktoken(description, model_name=tiktoken_model_name)
    if len(tokens) < summary_max_tokens:  # No need for summary
        return description
    prompt_template = PROMPTS["summarize_entity_descriptions"]
    use_description = decode_tokens_by_tiktoken(
        tokens[:llm_max_tokens], model_name=tiktoken_model_name
    )
    context_base = dict(
        entity_name=entity_or_relation_name,
        description_list=use_description.split(GRAPH_FIELD_SEP),
    )
    use_prompt = prompt_template.format(**context_base)
    logger.debug(f"Trigger summary: {entity_or_relation_name}")
    summary = await use_llm_func(use_prompt, max_tokens=summary_max_tokens)
    return summary


async def _handle_single_entity_extraction(
    record_attributes: list[str],
    chunk_key: str,
):
    if len(record_attributes) < 5 or record_attributes[0] != '"entity"':
        return None
    # add this record as a node in the G
    entity_name = clean_str(record_attributes[1].upper())
    if not entity_name.strip():
        return None
    entity_type = clean_str(record_attributes[2].upper())
    entity_time = clean_str(record_attributes[3])
    entity_description = clean_str(record_attributes[4])
    entity_source_id = chunk_key
    return dict(
        entity_name=entity_name,
        entity_type=entity_type,
        entity_time=entity_time,
        description=entity_description,
        source_id=entity_source_id,
    )


async def _handle_single_relationship_extraction(
    record_attributes: list[str],
    chunk_key: str,
):
    if len(record_attributes) < 5 or record_attributes[0] != '"relationship"':
        return None
    # add this record as edge
    source = clean_str(record_attributes[1].upper())
    target = clean_str(record_attributes[2].upper())
    edge_description = clean_str(record_attributes[3])
    edge_source_id = chunk_key
    weight = (
        float(record_attributes[-1]) if is_float_regex(record_attributes[-1]) else 1.0
    )
    return dict(
        src_id=source,
        tgt_id=target,
        weight=weight,
        description=edge_description,
        source_id=edge_source_id,
    )


async def _merge_nodes_then_upsert(
    entity_name: str,
    nodes_data: list[dict],
    knwoledge_graph_inst: BaseGraphStorage,
    global_config: dict,
):
    already_entitiy_types = []
    already_source_ids = []
    already_description = []

    already_node = await knwoledge_graph_inst.get_node(entity_name)
    if already_node is not None:
        already_entitiy_types.append(already_node["entity_type"])
        already_source_ids.extend(
            split_string_by_multi_markers(already_node["source_id"], [GRAPH_FIELD_SEP])
        )
        already_description.append(already_node["description"])
    if not nodes_data:
        return
    entity_type = sorted(
        Counter(
            [dp["entity_type"] for dp in nodes_data] + already_entitiy_types
        ).items(),
        key=lambda x: x[1],
        reverse=True,
    )[0][0]
    description = GRAPH_FIELD_SEP.join(
        sorted(set([dp["description"] for dp in nodes_data] + already_description))
    )
    source_id = GRAPH_FIELD_SEP.join(
        set([dp["source_id"] for dp in nodes_data] + already_source_ids)
    )
    description = await _handle_entity_relation_summary(
        entity_name, description, global_config
    )
    entity_time=' '.join(sorted(set([dp["entity_time"] for dp in nodes_data])))
    node_data = dict(
        entity_name=entity_name,
        entity_time=entity_time,
        entity_type=entity_type,
        description=description,
        source_id=source_id,
    )
    await knwoledge_graph_inst.upsert_node(
        entity_name,
        node_data=node_data,
    )
    node_data["entity_name"] = entity_name
    return node_data


async def _merge_edges_then_upsert(
    src_id: str,
    tgt_id: str,
    edges_data: list[dict],
    knwoledge_graph_inst: BaseGraphStorage,
    global_config: dict,
):
    already_weights = []
    already_source_ids = []
    already_description = []
    already_order = []
    if await knwoledge_graph_inst.has_edge(src_id, tgt_id):
        already_edge = await knwoledge_graph_inst.get_edge(src_id, tgt_id)
        already_weights.append(already_edge["weight"])
        already_source_ids.extend(
            split_string_by_multi_markers(already_edge["source_id"], [GRAPH_FIELD_SEP])
        )
        already_description.append(already_edge["description"])
        already_order.append(already_edge.get("order", 1))

    # [numberchiffre]: `Relationship.order` is only returned from DSPy's predictions
    order = min([dp.get("order", 1) for dp in edges_data] + already_order)
    weight = sum([dp["weight"] for dp in edges_data] + already_weights)
    description = GRAPH_FIELD_SEP.join(
        sorted(set([dp["description"] for dp in edges_data] + already_description))
    )
    source_id = GRAPH_FIELD_SEP.join(
        set([dp["source_id"] for dp in edges_data] + already_source_ids)
    )
    for need_insert_id in [src_id, tgt_id]:
        if not (await knwoledge_graph_inst.has_node(need_insert_id)):
            await knwoledge_graph_inst.upsert_node(
                need_insert_id,
                node_data={
                    "source_id": source_id,
                    "description": description,
                    "entity_type": '"UNKNOWN"',
                },
            )
    description = await _handle_entity_relation_summary(
        (src_id, tgt_id), description, global_config
    )
    await knwoledge_graph_inst.upsert_edge(
        src_id,
        tgt_id,
        edge_data=dict(
            weight=weight, description=description, source_id=source_id, order=order
        ),
    )


async def extract_entities(
    chunks: dict[str, TextChunkSchema],
    knwoledge_graph_inst: BaseGraphStorage,
    entity_vdb: BaseVectorStorage,
    global_config: dict,
    using_amazon_bedrock: bool=False,
) -> Union[BaseGraphStorage, None]:
    use_llm_func: callable = global_config["best_model_func"]
    entity_extract_max_gleaning = global_config["entity_extract_max_gleaning"]

    ordered_chunks = list(chunks.items())

    entity_extract_prompt = PROMPTS["entity_extraction"]
    context_base = dict(
        tuple_delimiter=PROMPTS["DEFAULT_TUPLE_DELIMITER"],
        record_delimiter=PROMPTS["DEFAULT_RECORD_DELIMITER"],
        completion_delimiter=PROMPTS["DEFAULT_COMPLETION_DELIMITER"],
        entity_types=",".join(PROMPTS["DEFAULT_ENTITY_TYPES"]),
    )
    continue_prompt = PROMPTS["entiti_continue_extraction"]
    if_loop_prompt = PROMPTS["entiti_if_loop_extraction"]

    already_processed = 0
    already_entities = 0
    already_relations = 0

    async def _process_single_content(chunk_key_dp: tuple[str, TextChunkSchema]):
        nonlocal already_processed, already_entities, already_relations
        chunk_key = chunk_key_dp[0]
        chunk_dp = chunk_key_dp[1]
        content = chunk_dp["content"]
        hint_prompt = entity_extract_prompt.format(**context_base, input_text=content)
        final_result = await use_llm_func(hint_prompt)
        if isinstance(final_result, list):
            final_result = final_result[0]["text"]

        history = pack_user_ass_to_openai_messages(hint_prompt, final_result, using_amazon_bedrock)
        for now_glean_index in range(entity_extract_max_gleaning):
            glean_result = await use_llm_func(continue_prompt, history_messages=history)

            history += pack_user_ass_to_openai_messages(continue_prompt, glean_result, using_amazon_bedrock)
            final_result += glean_result
            if now_glean_index == entity_extract_max_gleaning - 1:
                break

            if_loop_result: str = await use_llm_func(
                if_loop_prompt, history_messages=history
            )
            if_loop_result = if_loop_result.strip().strip('"').strip("'").lower()
            if if_loop_result != "yes":
                break

        records = split_string_by_multi_markers(
            final_result,
            [context_base["record_delimiter"], context_base["completion_delimiter"]],
        )

        maybe_nodes = defaultdict(list)
        maybe_edges = defaultdict(list)
        for record in records:
            record = re.search(r"\((.*)\)", record)
            if record is None:
                continue
            record = record.group(1)
            record_attributes = split_string_by_multi_markers(
                record, [context_base["tuple_delimiter"]]
            )
            if_entities = await _handle_single_entity_extraction(
                record_attributes, chunk_key
            )
            if if_entities is not None:
                maybe_nodes[if_entities["entity_name"]].append(if_entities)
                continue

            if_relation = await _handle_single_relationship_extraction(
                record_attributes, chunk_key
            )
            if if_relation is not None:
                maybe_edges[(if_relation["src_id"], if_relation["tgt_id"])].append(
                    if_relation
                )
        already_processed += 1
        already_entities += len(maybe_nodes)
        already_relations += len(maybe_edges)
        now_ticks = PROMPTS["process_tickers"][
            already_processed % len(PROMPTS["process_tickers"])
        ]
        print(
            f"{now_ticks} Processed {already_processed}({already_processed*100//len(ordered_chunks)}%) chunks,  {already_entities} entities(duplicated), {already_relations} relations(duplicated)\r",
            end="",
            flush=True,
        )
        return dict(maybe_nodes), dict(maybe_edges)

    # use_llm_func is wrapped in ascynio.Semaphore, limiting max_async callings
    results = await asyncio.gather(
        *[_process_single_content(c) for c in ordered_chunks]
    )
    # print()  # clear the progress bar
    maybe_nodes = defaultdict(list)
    maybe_edges = defaultdict(list)
    for m_nodes, m_edges in results:
        for k, v in m_nodes.items():
            maybe_nodes[k].extend(v)
        for k, v in m_edges.items():
            # it's undirected graph
            maybe_edges[tuple(sorted(k))].extend(v)
    all_entities_data = await asyncio.gather(
        *[
            _merge_nodes_then_upsert(k, v, knwoledge_graph_inst, global_config)
            for k, v in maybe_nodes.items()
        ]
    )
    await asyncio.gather(
        *[
            _merge_edges_then_upsert(k[0], k[1], v, knwoledge_graph_inst, global_config)
            for k, v in maybe_edges.items()
        ]
    )
    if not len(all_entities_data):
        logger.warning("Didn't extract any entities, maybe your LLM is not working")
        return None
    if entity_vdb is not None:
        data_for_vdb = {
            compute_mdhash_id(dp["entity_name"], prefix="ent-"): {
                "content": dp["entity_name"] + dp["description"],
                "entity_name": dp["entity_name"],
                "entity_time": dp["entity_time"]
            }
            for dp in all_entities_data
        }
        await entity_vdb.upsert(data_for_vdb)
    return knwoledge_graph_inst


def remove_quotes(d):
    # Iterate through the dictionary
    new_dict = {}
    for key, value in d.items():
        # Remove quotes from the keys
        if isinstance(key,tuple):
            new_key = tuple(k.strip('"') for k in key)
        else:
            new_key = key.strip('"')
        if isinstance(value,list):
            new_value = [remove_quotes(item) if isinstance(item,dict) else item for item in value]
        else:
            new_value = value.strip('"') if isinstance(value, str) else value
        # Add the new key and value to the new dictionary
        new_dict[new_key] = new_value

    return new_dict


def get_connection():
    host = "localhost"
    port = "5432"
    database = "history"
    user = "postgres"
    password = "postgres"
    return psycopg2.connect(
        host=host,
        port=port,
        dbname=database,
        user=user,
        password=password
    )

# Function to create the events table if it does not exist
def create_postgres_table():
    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor()

        create_table_query = '''
        CREATE TABLE IF NOT EXISTS lichsu12 (
            entity_hash_id TEXT PRIMARY KEY,
            entity_name VARCHAR(255) NOT NULL,
            entity_time TIMESTAMP,
            entity_description TEXT
        );
        '''
        cursor.execute(create_table_query)
        connection.commit()
        print("Table 'lichsu12' is ready (created if not exists).")

    except Exception as e:
        print(f"Error creating table: {e}")

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def parse_date(date):
    date_str = str(date)
    if date_str is None or date_str.lower() == 'na':  # Handle None and 'None'
        return None
    # Try different date formats
    date_formats = [
        "%Y",  # Year only (e.g., 1945)
        "%d/%m/%Y",  # Day/Month/Year (e.g., 2/9/1945)
        "%m/%Y",  # Month/Year (e.g., 9/1945)
        "%Y-%m-%d",  # Standard ISO format (e.g., 1945-09-02)
    ]
    for date_format in date_formats:
        try:
            processed_date = datetime.strptime(date_str, date_format)
            return processed_date
        except ValueError:
            continue

    # If none of the formats match, return None
    return None
# Function to insert rows with hash as primary key
def insert_rows(all_entities_data):
    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor()

        # Prepare the data for insertion with hash as the primary key
        data_for_postgres = [
            (
                key,
                all_entities_data[key]["entity_name"],
                parse_date(all_entities_data[key]["entity_time"]),  # Handle various date formats
                all_entities_data[key]["content"][len(all_entities_data[key]["entity_name"]):]
            )
            for key in all_entities_data.keys()
        ]
        print(data_for_postgres)
        insert_query = '''
        INSERT INTO lichsu12 (entity_hash_id, entity_name, entity_time, entity_description)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (entity_hash_id)
        DO UPDATE SET 
            entity_name = EXCLUDED.entity_name,
            entity_time = EXCLUDED.entity_time,
            entity_description = EXCLUDED.entity_description;
        '''

        cursor.executemany(insert_query, data_for_postgres)
        connection.commit()
        print(f"Inserted/Updated {len(all_entities_data)} rows.")

    except Exception as e:
        print(f"Error inserting/updating rows: {e}")

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


async def custom_extract_entities(
    chunks: dict[str, TextChunkSchema],
    knwoledge_graph_inst: BaseGraphStorage,
    entity_vdb: BaseVectorStorage,
    global_config: dict,
    using_amazon_bedrock: bool=False,
) -> Union[BaseGraphStorage, None]:
    use_llm_func: callable = global_config["best_model_func"]
    entity_extract_max_gleaning = global_config["entity_extract_max_gleaning"]

    ordered_chunks = list(chunks.items())

    entity_extract_prompt = PROMPTS["entity_extraction"]
    context_base = dict(
        tuple_delimiter=PROMPTS["DEFAULT_TUPLE_DELIMITER"],
        record_delimiter=PROMPTS["DEFAULT_RECORD_DELIMITER"],
        completion_delimiter=PROMPTS["DEFAULT_COMPLETION_DELIMITER"],
        entity_types=",".join(PROMPTS["DEFAULT_ENTITY_TYPES"]),
    )
    continue_prompt = PROMPTS["entiti_continue_extraction"]
    if_loop_prompt = PROMPTS["entiti_if_loop_extraction"]

    already_processed = 0
    already_entities = 0
    already_relations = 0

    async def _process_single_content(chunk_key_dp: tuple[str, TextChunkSchema]):
        nonlocal already_processed, already_entities, already_relations
        chunk_key = chunk_key_dp[0]
        chunk_dp = chunk_key_dp[1]
        content = chunk_dp["content"]
        hint_prompt = entity_extract_prompt.format(**context_base, input_text=content)
        final_result = await use_llm_func(hint_prompt)
        if isinstance(final_result, list):
            final_result = final_result[0]["text"]

        history = pack_user_ass_to_openai_messages(hint_prompt, final_result, using_amazon_bedrock)
        for now_glean_index in range(entity_extract_max_gleaning):
            glean_result = await use_llm_func(continue_prompt, history_messages=history)

            history += pack_user_ass_to_openai_messages(continue_prompt, glean_result, using_amazon_bedrock)
            final_result += glean_result
            if now_glean_index == entity_extract_max_gleaning - 1:
                break

            if_loop_result: str = await use_llm_func(
                if_loop_prompt, history_messages=history
            )
            if_loop_result = if_loop_result.strip().strip('"').strip("'").lower()
            if if_loop_result != "yes":
                break

        records = split_string_by_multi_markers(
            final_result,
            [context_base["record_delimiter"], context_base["completion_delimiter"]],
        )

        maybe_nodes = defaultdict(list)
        maybe_edges = defaultdict(list)
        for record in records:
            record = re.search(r"\((.*)\)", record)
            if record is None:
                continue
            record = record.group(1)
            record_attributes = split_string_by_multi_markers(
                record, [context_base["tuple_delimiter"]]
            )
            if_entities = await _handle_single_entity_extraction(
                record_attributes, chunk_key
            )
            if if_entities is not None:
                maybe_nodes[if_entities["entity_name"]].append(if_entities)
                continue

            if_relation = await _handle_single_relationship_extraction(
                record_attributes, chunk_key
            )
            if if_relation is not None:
                maybe_edges[(if_relation["src_id"], if_relation["tgt_id"])].append(
                    if_relation
                )
        already_processed += 1
        already_entities += len(maybe_nodes)
        already_relations += len(maybe_edges)
        now_ticks = PROMPTS["process_tickers"][
            already_processed % len(PROMPTS["process_tickers"])
        ]
        print(
            f"{now_ticks} Processed {already_processed}({already_processed*100//len(ordered_chunks)}%) chunks,  {already_entities} entities(duplicated), {already_relations} relations(duplicated)\r",
            end="",
            flush=True,
        )
        return dict(maybe_nodes), dict(maybe_edges)

    # use_llm_func is wrapped in ascynio.Semaphore, limiting max_async callings
    results = await asyncio.gather(
        *[_process_single_content(c) for c in ordered_chunks]
    )
    # print()  # clear the progress bar
    maybe_nodes = defaultdict(list)
    maybe_edges = defaultdict(list)
    for m_nodes, m_edges in results:
        for k, v in m_nodes.items():
            maybe_nodes[k].extend(v)
        for k, v in m_edges.items():
            # it's undirected graph
            maybe_edges[tuple(sorted(k))].extend(v)
    ### Entity alignment
    maybe_nodes = defaultdict(list,remove_quotes(maybe_nodes))
    maybe_edges = defaultdict(list,remove_quotes(maybe_edges))
    #
    # import json
    print("Dump nodes and entities into json file")
    with open(f"{global_config['working_dir']}/maybe_nodes.json", 'w') as file:
        file.write(str(maybe_nodes))
    with open(f"{global_config['working_dir']}/maybe_edges.json", 'w') as file:
        file.write(str(maybe_edges))
    entity_list=""
    for entity_name in maybe_nodes.keys():
        entity_list += entity_name
    merge_entity_prompt=PROMPTS['merge_entity'].format(entity_list=entity_list)
    merge_entity_result=await use_llm_func(merge_entity_prompt)
    merge_entity_result = merge_entity_result.replace("```","")
    print(f"Duplicated entity info: \n {merge_entity_result}")
    merge_entity_result = merge_entity_result.split("<SEP>")
    for entity_group in merge_entity_result:
        entity_group = entity_group.replace("\n", "")
        entity_atom = entity_group.split('-->')
        if len(entity_atom) != 2:
            continue
        entities = [item.strip() for item in entity_atom[0].strip('[]').split(',')]
        entities = list(set(entities))
        target_entity = entity_atom[1]
        if not target_entity:
            continue
        # Merge node
        if target_entity in entities:
            entities.remove(target_entity)
        for entity in entities:
            maybe_nodes[target_entity].extend(maybe_nodes[entity])
            del maybe_nodes[entity]
        for i in range(len(maybe_nodes[target_entity])):
            maybe_nodes[target_entity][i]['entity_name'] = target_entity
        # Merge edge
        for edge, description in maybe_edges:
            for entity in entities:
                if edge[0]==entity and entity != target_entity:
                    maybe_edges[(target_entity,edge[1])] = description
                    del maybe_edges[edge]
                elif edge[1]==entity and entity != target_entity:
                    maybe_edges[(edge[0], target_entity)] = description
                    del maybe_edges[edge]
    all_entities_data = await asyncio.gather(
        *[
            _merge_nodes_then_upsert(k, v, knwoledge_graph_inst, global_config)
            for k, v in maybe_nodes.items()
        ]
    )
    all_entities_data = [item for item in all_entities_data if item is not None]
    await asyncio.gather(
        *[
            _merge_edges_then_upsert(k[0], k[1], v, knwoledge_graph_inst, global_config)
            for k, v in maybe_edges.items()
        ]
    )
    if not len(all_entities_data):
        logger.warning("Didn't extract any entities, maybe your LLM is not working")
        return None
    print(f"all entities data:\n {all_entities_data}")
    if entity_vdb is not None:
        data_for_vdb = {
            compute_mdhash_id(dp["entity_name"], prefix="ent-"): {
                "content": dp["entity_name"] + dp["description"],
                "entity_name": dp["entity_name"],
                "entity_time": dp["entity_time"],
            }
            for dp in all_entities_data
        }
        create_postgres_table()
        insert_rows(data_for_vdb)
        await entity_vdb.upsert(data_for_vdb)

    return knwoledge_graph_inst


def _pack_single_community_by_sub_communities(
    community: SingleCommunitySchema,
    max_token_size: int,
    already_reports: dict[str, CommunitySchema],
) -> tuple[str, int]:
    # TODO
    all_sub_communities = [
        already_reports[k] for k in community["sub_communities"] if k in already_reports
    ]
    all_sub_communities = sorted(
        all_sub_communities, key=lambda x: x["occurrence"], reverse=True
    )
    may_trun_all_sub_communities = truncate_list_by_token_size(
        all_sub_communities,
        key=lambda x: x["report_string"],
        max_token_size=max_token_size,
    )
    sub_fields = ["id", "report", "rating", "importance"]
    sub_communities_describe = list_of_list_to_csv(
        [sub_fields]
        + [
            [
                i,
                c["report_string"],
                c["report_json"].get("rating", -1),
                c["occurrence"],
            ]
            for i, c in enumerate(may_trun_all_sub_communities)
        ]
    )
    already_nodes = []
    already_edges = []
    for c in may_trun_all_sub_communities:
        already_nodes.extend(c["nodes"])
        already_edges.extend([tuple(e) for e in c["edges"]])
    return (
        sub_communities_describe,
        len(encode_string_by_tiktoken(sub_communities_describe)),
        set(already_nodes),
        set(already_edges),
    )


async def _pack_single_community_describe(
    knwoledge_graph_inst: BaseGraphStorage,
    community: SingleCommunitySchema,
    max_token_size: int = 12000,
    already_reports: dict[str, CommunitySchema] = {},
    global_config: dict = {},
) -> str:
    nodes_in_order = sorted(community["nodes"])
    edges_in_order = sorted(community["edges"], key=lambda x: x[0] + x[1])

    nodes_data = await asyncio.gather(
        *[knwoledge_graph_inst.get_node(n) for n in nodes_in_order]
    )
    edges_data = await asyncio.gather(
        *[knwoledge_graph_inst.get_edge(src, tgt) for src, tgt in edges_in_order]
    )
    node_fields = ["id", "entity", "type", "description", "degree"]
    edge_fields = ["id", "source", "target", "description", "rank"]
    nodes_list_data = [
        [
            i,
            node_name,
            node_data.get("entity_type", "UNKNOWN"),
            node_data.get("description", "UNKNOWN"),
            await knwoledge_graph_inst.node_degree(node_name),
        ]
        for i, (node_name, node_data) in enumerate(zip(nodes_in_order, nodes_data))
    ]
    nodes_list_data = sorted(nodes_list_data, key=lambda x: x[-1], reverse=True)
    nodes_may_truncate_list_data = truncate_list_by_token_size(
        nodes_list_data, key=lambda x: x[3], max_token_size=max_token_size // 2
    )
    edges_list_data = [
        [
            i,
            edge_name[0],
            edge_name[1],
            edge_data.get("description", "UNKNOWN"),
            await knwoledge_graph_inst.edge_degree(*edge_name),
        ]
        for i, (edge_name, edge_data) in enumerate(zip(edges_in_order, edges_data))
    ]
    edges_list_data = sorted(edges_list_data, key=lambda x: x[-1], reverse=True)
    edges_may_truncate_list_data = truncate_list_by_token_size(
        edges_list_data, key=lambda x: x[3], max_token_size=max_token_size // 2
    )

    truncated = len(nodes_list_data) > len(nodes_may_truncate_list_data) or len(
        edges_list_data
    ) > len(edges_may_truncate_list_data)

    # If context is exceed the limit and have sub-communities:
    report_describe = ""
    need_to_use_sub_communities = (
        truncated and len(community["sub_communities"]) and len(already_reports)
    )
    force_to_use_sub_communities = global_config["addon_params"].get(
        "force_to_use_sub_communities", False
    )
    if need_to_use_sub_communities or force_to_use_sub_communities:
        logger.debug(
            f"Community {community['title']} exceeds the limit or you set force_to_use_sub_communities to True, using its sub-communities"
        )
        report_describe, report_size, contain_nodes, contain_edges = (
            _pack_single_community_by_sub_communities(
                community, max_token_size, already_reports
            )
        )
        report_exclude_nodes_list_data = [
            n for n in nodes_list_data if n[1] not in contain_nodes
        ]
        report_include_nodes_list_data = [
            n for n in nodes_list_data if n[1] in contain_nodes
        ]
        report_exclude_edges_list_data = [
            e for e in edges_list_data if (e[1], e[2]) not in contain_edges
        ]
        report_include_edges_list_data = [
            e for e in edges_list_data if (e[1], e[2]) in contain_edges
        ]
        # if report size is bigger than max_token_size, nodes and edges are []
        nodes_may_truncate_list_data = truncate_list_by_token_size(
            report_exclude_nodes_list_data + report_include_nodes_list_data,
            key=lambda x: x[3],
            max_token_size=(max_token_size - report_size) // 2,
        )
        edges_may_truncate_list_data = truncate_list_by_token_size(
            report_exclude_edges_list_data + report_include_edges_list_data,
            key=lambda x: x[3],
            max_token_size=(max_token_size - report_size) // 2,
        )
    nodes_describe = list_of_list_to_csv([node_fields] + nodes_may_truncate_list_data)
    edges_describe = list_of_list_to_csv([edge_fields] + edges_may_truncate_list_data)
    return f"""-----Reports-----
```csv
{report_describe}
```
-----Entities-----
```csv
{nodes_describe}
```
-----Relationships-----
```csv
{edges_describe}
```"""


def _community_report_json_to_str(parsed_output: dict) -> str:
    """refer official graphrag: index/graph/extractors/community_reports"""
    title = parsed_output.get("title", "Report")
    summary = parsed_output.get("summary", "")
    findings = parsed_output.get("findings", [])

    def finding_summary(finding: dict):
        if isinstance(finding, str):
            return finding
        return finding.get("summary")

    def finding_explanation(finding: dict):
        if isinstance(finding, str):
            return ""
        return finding.get("explanation")

    report_sections = "\n\n".join(
        f"## {finding_summary(f)}\n\n{finding_explanation(f)}" for f in findings
    )
    return f"# {title}\n\n{summary}\n\n{report_sections}"


async def generate_community_report(
    community_report_kv: BaseKVStorage[CommunitySchema],
    knwoledge_graph_inst: BaseGraphStorage,
    global_config: dict,
):
    llm_extra_kwargs = global_config["special_community_report_llm_kwargs"]
    use_llm_func: callable = global_config["best_model_func"]
    use_string_json_convert_func: callable = global_config[
        "convert_response_to_json_func"
    ]

    community_report_prompt = PROMPTS["community_report"]

    communities_schema = await knwoledge_graph_inst.community_schema()
    community_keys, community_values = list(communities_schema.keys()), list(
        communities_schema.values()
    )
    already_processed = 0

    async def _form_single_community_report(
        community: SingleCommunitySchema, already_reports: dict[str, CommunitySchema]
    ):
        nonlocal already_processed
        describe = await _pack_single_community_describe(
            knwoledge_graph_inst,
            community,
            max_token_size=global_config["best_model_max_token_size"],
            already_reports=already_reports,
            global_config=global_config,
        )
        prompt = community_report_prompt.format(input_text=describe)
        response = await use_llm_func(prompt, **llm_extra_kwargs)

        data = use_string_json_convert_func(response)
        already_processed += 1
        now_ticks = PROMPTS["process_tickers"][
            already_processed % len(PROMPTS["process_tickers"])
        ]
        print(
            f"{now_ticks} Processed {already_processed} communities\r",
            end="",
            flush=True,
        )
        return data

    levels = sorted(set([c["level"] for c in community_values]), reverse=True)
    logger.info(f"Generating by levels: {levels}")
    community_datas = {}
    for level in levels:
        this_level_community_keys, this_level_community_values = zip(
            *[
                (k, v)
                for k, v in zip(community_keys, community_values)
                if v["level"] == level
            ]
        )
        this_level_communities_reports = await asyncio.gather(
            *[
                _form_single_community_report(c, community_datas)
                for c in this_level_community_values
            ]
        )
        community_datas.update(
            {
                k: {
                    "report_string": _community_report_json_to_str(r),
                    "report_json": r,
                    **v,
                }
                for k, r, v in zip(
                    this_level_community_keys,
                    this_level_communities_reports,
                    this_level_community_values,
                )
            }
        )
    print()  # clear the progress bar
    await community_report_kv.upsert(community_datas)


async def _find_most_related_community_from_entities(
    node_datas: list[dict],
    query_param: QueryParam,
    community_reports: BaseKVStorage[CommunitySchema],
):
    related_communities = []
    for node_d in node_datas:
        if "clusters" not in node_d:
            continue
        related_communities.extend(json.loads(node_d["clusters"]))
    related_community_dup_keys = [
        str(dp["cluster"])
        for dp in related_communities
        if dp["level"] <= query_param.level
    ]
    related_community_keys_counts = dict(Counter(related_community_dup_keys))
    _related_community_datas = await asyncio.gather(
        *[community_reports.get_by_id(k) for k in related_community_keys_counts.keys()]
    )
    related_community_datas = {
        k: v
        for k, v in zip(related_community_keys_counts.keys(), _related_community_datas)
        if v is not None
    }
    related_community_keys = sorted(
        related_community_keys_counts.keys(),
        key=lambda k: (
            related_community_keys_counts[k],
            related_community_datas[k]["report_json"].get("rating", -1),
        ),
        reverse=True,
    )
    sorted_community_datas = [
        related_community_datas[k] for k in related_community_keys
    ]

    use_community_reports = truncate_list_by_token_size(
        sorted_community_datas,
        key=lambda x: x["report_string"],
        max_token_size=query_param.local_max_token_for_community_report,
    )
    if query_param.local_community_single_one:
        use_community_reports = use_community_reports[:1]
    return use_community_reports


async def _find_most_related_text_unit_from_entities(
    node_datas: list[dict],
    query_param: QueryParam,
    text_chunks_db: BaseKVStorage[TextChunkSchema],
    knowledge_graph_inst: BaseGraphStorage,
):
    text_units = [
        split_string_by_multi_markers(dp["source_id"], [GRAPH_FIELD_SEP])
        for dp in node_datas
    ]
    edges = await asyncio.gather(
        *[knowledge_graph_inst.get_node_edges(dp["entity_name"]) for dp in node_datas]
    )
    all_one_hop_nodes = set()
    for this_edges in edges:
        if not this_edges:
            continue
        all_one_hop_nodes.update([e[1] for e in this_edges])
    all_one_hop_nodes = list(all_one_hop_nodes)
    all_one_hop_nodes_data = await asyncio.gather(
        *[knowledge_graph_inst.get_node(e) for e in all_one_hop_nodes]
    )
    all_one_hop_text_units_lookup = {
        k: set(split_string_by_multi_markers(v["source_id"], [GRAPH_FIELD_SEP]))
        for k, v in zip(all_one_hop_nodes, all_one_hop_nodes_data)
        if v is not None
    }
    all_text_units_lookup = {}
    for index, (this_text_units, this_edges) in enumerate(zip(text_units, edges)):
        for c_id in this_text_units:
            if c_id in all_text_units_lookup:
                continue
            relation_counts = 0
            for e in this_edges:
                if (
                    e[1] in all_one_hop_text_units_lookup
                    and c_id in all_one_hop_text_units_lookup[e[1]]
                ):
                    relation_counts += 1
            all_text_units_lookup[c_id] = {
                "data": await text_chunks_db.get_by_id(c_id),
                "order": index,
                "relation_counts": relation_counts,
            }
    if any([v is None for v in all_text_units_lookup.values()]):
        logger.warning("Text chunks are missing, maybe the storage is damaged")
    all_text_units = [
        {"id": k, **v} for k, v in all_text_units_lookup.items() if v is not None
    ]
    all_text_units = sorted(
        all_text_units, key=lambda x: (x["order"], -x["relation_counts"])
    )
    all_text_units = truncate_list_by_token_size(
        all_text_units,
        key=lambda x: x["data"]["content"],
        max_token_size=query_param.local_max_token_for_text_unit,
    )
    all_text_units: list[TextChunkSchema] = [t["data"] for t in all_text_units]
    return all_text_units


async def _find_most_related_edges_from_entities(
    node_datas: list[dict],
    query_param: QueryParam,
    knowledge_graph_inst: BaseGraphStorage,
):
    all_related_edges = await asyncio.gather(
        *[knowledge_graph_inst.get_node_edges(dp["entity_name"]) for dp in node_datas]
    )
    
    all_edges = []
    seen = set()
    
    for this_edges in all_related_edges:
        for e in this_edges:
            sorted_edge = tuple(sorted(e))
            if sorted_edge not in seen:
                seen.add(sorted_edge)
                all_edges.append(sorted_edge) 
                
    all_edges_pack = await asyncio.gather(
        *[knowledge_graph_inst.get_edge(e[0], e[1]) for e in all_edges]
    )
    all_edges_degree = await asyncio.gather(
        *[knowledge_graph_inst.edge_degree(e[0], e[1]) for e in all_edges]
    )
    all_edges_data = [
        {"src_tgt": k, "rank": d, **v}
        for k, v, d in zip(all_edges, all_edges_pack, all_edges_degree)
        if v is not None
    ]
    all_edges_data = sorted(
        all_edges_data, key=lambda x: (x["rank"], x["weight"]), reverse=True
    )
    all_edges_data = truncate_list_by_token_size(
        all_edges_data,
        key=lambda x: x["description"],
        max_token_size=query_param.local_max_token_for_local_context,
    )
    return all_edges_data


def postgres_query_date(start_time: datetime, end_time: datetime, top_k: int = 20):
    connection = None
    cursor = None
    if start_time == None or end_time == None:
        return
    if start_time==end_time:
        start_time,end_time=start_time+relativedelta(months=-6), start_time+relativedelta(months=+6)
    try:
        # Establish connection
        connection = get_connection()
        cursor = connection.cursor()

        # Query to select entities in the given time period
        query = '''
        SELECT entity_hash_id, entity_name, entity_time, entity_description
        FROM lichsu12
        WHERE entity_time BETWEEN %s AND %s
        LIMIT %s;
        '''
        # Execute the query with the provided start_time, end_time, and top_k limit
        cursor.execute(query, (start_time, end_time, top_k))

        # Fetch all results
        results = cursor.fetchall()
        return [
            {
                "id": result[0],  # entity_hash_id
                "entity_name": result[1],
                "entity_time": result[2],
                "entity_description": result[3],
                "distance": 0.5
            }
            for result in results
        ]

    except Exception as e:
        print(f"Error querying PostgreSQL: {e}")
        return []

    finally:
        # Ensure resources are released
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def postgres_query_entity_name(entity_name: str):
    connection = None
    cursor = None
    try:
        # Establish connection
        connection = get_connection()
        cursor = connection.cursor()

        # Query to select entities in the given time period
        query = '''
        SELECT entity_hash_id, entity_name, entity_time, entity_description
        FROM lichsu12
        WHERE entity_name = %s;
        '''
        # Execute the query with the provided start_time, end_time, and top_k limit
        cursor.execute(query, (entity_name,))

        # Fetch all results
        results = cursor.fetchall()
        return [
            {
                "id": result[0],  # entity_hash_id
                "entity_name": result[1],
                "entity_time": result[2],
                "entity_description": result[3],
            }
            for result in results
        ]

    except Exception as e:
        print(f"Error querying PostgreSQL: {e}")
        return []

    finally:
        # Ensure resources are released
        if cursor:
            cursor.close()
        if connection:
            connection.close()

async def _build_local_query_context(
    query,
    knowledge_graph_inst: BaseGraphStorage,
    entities_vdb: BaseVectorStorage,
    community_reports: BaseKVStorage[CommunitySchema],
    text_chunks_db: BaseKVStorage[TextChunkSchema],
    query_param: QueryParam,
):
    from ._llm import gpt_4o_mini_complete, gpt_4o_complete

    results = await entities_vdb.query(query, top_k=query_param.top_k)
    for i in range(len(results)):
        entity_name = results[i]['entity_name']
        entity_info = postgres_query_entity_name(entity_name)
        try:
            results[i]['entity_description'] = entity_info[0]['entity_description']
        except Exception as e:
            print(f"#### Cannot extract entity description for {entity_name} with error {e}")
            results[i]['entity_description'] = "None"

    query_period_query = PROMPTS['time_extraction'].format(query=query)
    time_period= await gpt_4o_mini_complete(query_period_query)
    try:
        start_time, end_time = time_period.split("-")
        time_results = postgres_query_date(start_time=parse_date(start_time), end_time=parse_date(end_time))
        if time_results != None:
            results.extend(time_results)
    except:
        pass
    ### rerank using LLM
    try:
        rerank_entity_query=f"""
    Tôi đang có danh sách các thực thể và các mô tả của các thực thể về 1 chủ đề lịch sử. Bạn hãy giúp tôi lọc ra những thực thể hữu ích để trả lời câu hỏi được đưa ra.
    Dữ liệu đầu ra là danh sách tên các thực thể được in hoa và giống với dữ liệu đầu vào được ngăn cách với nhau bởi dấu |
###################### Ví dụ ######################
    Câu hỏi:
Năm 1936, ở Việt Nam các ủy ban hành động được thành lập nhằm mục đích gì?
A.	Để lập ra các hội ái hữu thay cho Công hội đỏ, Nông hội đỏ.
B.	Chuẩn bị mọi mặt cho khởi nghĩa giành chính quyền.
c. Biểu dương lực lượng khi đón phái viên của Chính phủ Pháp.
D. Thu thập “dân nguyện” tiến tới Đông Dương Đại hội.
    Danh sách các thực thể:
['entity_name': '"ĐẢNG DÂN CHỦ VIỆT NAM"', 'id': 'ent-8c8e0e2065849be3fc86e0ff6f568220', 'distance': 0.5656490325927734, 'entity_description': '"Đảng Dân chủ Việt Nam được thành lập nhằm tập hợp lực lượng chính trị đa dạng trong cuộc kháng chiến và xây dựng đất nước, tham gia vào Mặt trận Việt Minh chống thực dân Pháp."', 'entity_name': '"PHONG TRÀO DÂN CHỦ 1936 – 1939"', 'id': 'ent-186a43b9c6b23482682e7501c30faa93', 'distance': 0.5586332082748413, 'entity_description': '"Phong trào Dân chủ 1936 – 1939 là một cuộc vận động quần chúng lớn, do Đảng Cộng sản Đông Dương lãnh đạo, nhằm mở rộng quyền lợi dân sinh, dân chủ cho nhân dân lao động. Phong trào đã buộc chính quyền thực dân phải nhượng bộ một số yêu sách cụ thể và giúp quần chúng giác ngộ về chính trị."<SEP>"Phong trào Dân chủ 1936 – 1939 là một cuộc vận động quần chúng lớn, do Đảng Cộng sản Đông Dương lãnh đạo, nhằm mở rộng quyền lợi dân sinh, dân chủ cho nhân dân lao động. Phong trào đã buộc chính quyền thực dân phải nhượng bộ một số yêu sách cụ thể và giúp quần chúng giác ngộ về chính trị."<SEP>"Phong trào dân chủ 1936 – 1939 thể hiện sự phát triển mạnh mẽ của các phong trào dân chủ tại Việt Nam, với sự tham gia của nhiều tổ chức chính trị và xã hội nhằm yêu cầu thực dân Pháp thực hiện những cải cách chính trị và xã hội."<SEP>"Phong trào dân chủ 1936 – 1939 thể hiện sự phát triển mạnh mẽ của các phong trào dân chủ tại Việt Nam, với sự tham gia của nhiều tổ chức chính trị và xã hội nhằm yêu cầu thực dân Pháp thực hiện những cải cách chính trị và xã hội."', 'entity_name': '"CHÍNH PHỦ NHÂN DÂN"', 'id': 'ent-644009ac01153664cd96d1bf5a639463', 'distance': 0.5334857702255249, 'entity_description': '"Chính phủ nhân dân của nước Việt Nam Dân chủ Cộng hoà được thành lập trong bối cảnh kháng chiến chống Pháp và Nhật, nhằm tạo ra một cơ chế lãnh đạo chính thức cho phong trào cách mạng và giải phóng dân tộc."', 'entity_name': '"THÁNG 9 - 1936"', 'id': 'ent-96e7da1755d62540e4beddba8b73ad52', 'distance': 0.5297252535820007, 'entity_description': '"Tháng 9 - 1936 là thời điểm mà chính quyền thực dân ra lệnh giải tán các ủy ban hành động và cấm các cuộc hội họp của nhân dân, đánh dấu bước tiến mới trong việc đàn áp phong trào cách mạng tại Đông Dương."', 'entity_name': '"HỘI LIÊN VIỆT"', 'id': 'ent-becbaacfb39c05408bddbcc20bf3ee40', 'distance': 0.520359992980957, 'entity_description': '"Hội Liên Việt là tổ chức được thành lập nhằm thống nhất các lực lượng kháng chiến, kết hợp giữa các tổ chức chính trị khác nhau để nâng cao sức mạnh chiến đấu chống thực dân Pháp."', 'entity_name': '"HỘI LIÊN HIỆP QUỐC DÂN VIỆT NAM (LIÊN VIỆT)"', 'id': 'ent-3a336af2c36c760053c2dc8902a0fba2', 'distance': 0.5199624300003052, 'entity_description': '"Hội Liên hiệp quốc dân Việt Nam (Liên Việt) là một tổ chức chính trị được thành lập trong bối cảnh kháng chiến chống Pháp, nhằm mục đích tập hợp lực lượng chính trị yêu nước, thống nhất các phong trào cách mạng và tăng cường sức mạnh kháng chiến."', 'entity_name': '"HỘI NGHỊ BAN CHẤP HÀNH TRUNG ƯƠNG ĐẢNG CỘNG SẢN ĐÔNG DƯƠNG THÁNG 7 – 1936"', 'id': 'ent-71318cdf16440613d8f5e1fe86b6ea14', 'distance': 0.5148401260375977, 'entity_description': '"Hội nghị này có ý nghĩa quan trọng trong việc xác định đường lối đấu tranh của Đảng Cộng sản Đông Dương, với mục tiêu chống đế quốc, chống phong kiến, và đòi hỏi các quyền tự do, dân sinh, dân chủ cho nhân dân. Hội nghị quyết định thành lập Mặt trận Thống nhất nhân dân phản đế Đông Dương và kêu gọi các đảng phái cùng nhân dân tham gia phong trào đấu tranh."', 'entity_name': '"ĐỘI TỰ VỆ VÀ CỨU TẾ ĐỎ"', 'id': 'ent-13e09a0cb0934215470e7619b4f99a5c', 'distance': 0.5086166262626648, 'entity_description': '"Đội tự vệ và cứu tế đỏ là lực lượng được thành lập nhằm bảo vệ người dân và hỗ trợ trong các hoạt động cứu trợ, thể hiện tinh thần đoàn kết và trợ giúp của Đảng trong công cuộc đấu tranh."', 'entity_name': '"ĐẢNG CỘNG SẢN"', 'id': 'ent-0794f24ae7ff52435953f177acf7c3bb', 'distance': 0.5042251944541931, 'entity_description': '"Đảng Cộng sản Đông Dương là lực lượng lãnh đạo và tổ chức các phong trào đấu tranh chống thực dân Pháp. Đảng giữ vai trò quyết định trong việc định hướng chiến lược cách mạng, đặc biệt là việc đoàn kết giai cấp công nhân và nông dân."', 'entity_name': '"ĐẢNG CỘNG SẢN VIỆT NAM"', 'id': 'ent-d56367430c17d0f1608c707af2835f2c', 'distance': 0.5002216100692749, 'entity_description': 'Đảng Cộng sản Việt Nam, được thành lập vào năm 1930 dưới sự sáng lập của Nguyễn Ái Quốc, là lực lượng lãnh đạo chính trị của cách mạng Việt Nam. Đảng đóng vai trò quan trọng trong việc tổ chức và lãnh đạo các cuộc kháng chiến chống thực dân Pháp và Mỹ, định hướng cho phong trào cách mạng, cũng như xây dựng chính quyền cách mạng. Đảng đại diện cho giai cấp vô sản và các tầng lớp nhân dân lao động khác, là tổ chức chính trị lãnh đạo cuộc đấu tranh giành độc lập và tự do cho dân tộc.\n\nLịch sử của Đảng gắn liền với nhiều giai đoạn phát triển của cách mạng Việt Nam, trong đó có việc kết hợp chủ nghĩa Mác-Lênin với phong trào công nhân và yêu nước. Đảng đã thiết lập các đường lối, chủ trương nhằm kháng chiến thành công và thúc đẩy phát triển đất nước sau chiến tranh. Ngoài ra, Đảng Cộng sản Việt Nam cũng góp phần vào sự nghiệp đổi mới từ giữa những năm 1980, xác định hướng đi và chiến lược phát triển lâu dài của nền kinh tế quốc dân.\n\nThông qua các đại hội đảng, Đảng Cộng sản Việt Nam đã đưa ra những quyết sách lớn trong việc phát triển kinh tế - xã hội, khẳng định vai trò lãnh đạo trong các hoạt động kháng chiến cũng như trong công cuộc phát triển quốc gia.', 'entity_name': '"CUỘC “KHỦNG BỐ TRẮNG” CỦA THỰC DÂN PHÁP"', 'id': 'ent-0a7e4e3f13af8934dc3b1c6a0aae27e2', 'distance': 0.4979051649570465, 'entity_description': '"Cuộc khủng bố trắng là một chính sách của thực dân Pháp nhằm đàn áp phong trào cách mạng và phong trào yêu nước ở Việt Nam, đặc biệt những năm 1930 - 1931, đã dẫn tới nhiều cuộc nổi dậy của quần chúng."', 'entity_name': '"CHÍNH QUYỀN THỰC DÂN"', 'id': 'ent-8f27fa9ba50ad3ae58811576ee6d7016', 'distance': 0.4966307282447815, 'entity_description': '"Chính quyền thực dân Pháp đã thiết lập các chính sách nhằm duy trì quyền kiểm soát và khai thác tối đa tài nguyên từ thuộc địa, gây khó khăn cho cuộc sống của người dân địa phương, đồng thời tạo điều kiện cho tư bản Pháp chiếm đoạt ruộng đất của nông dân."<SEP>"Chính quyền thực dân Pháp đã thiết lập các chính sách nhằm duy trì quyền kiểm soát và khai thác tối đa tài nguyên từ thuộc địa, gây khó khăn cho cuộc sống của người dân địa phương, đồng thời tạo điều kiện cho tư bản Pháp chiếm đoạt ruộng đất của nông dân."<SEP>"Chính quyền thực dân là hệ thống chính quyền do thực dân Pháp thiết lập, hoạt động nhằm duy trì sự cai trị và khai thác tài nguyên tại Việt Nam, thường xuyên phải đối mặt với các cuộc kháng chiến của nhân dân."<SEP>"Chính quyền thực dân tại Đông Dương là lực lượng cai trị, phản động nghịch lại các yêu cầu dân chủ và dân sinh, đã thực hiện nhiều biện pháp hạn chế quyền tự do của người dân, trong đó có việc cấm các cuộc hội họp, mít tinh của quần chúng."<SEP>"Chính quyền thực dân là hệ thống chính quyền do thực dân Pháp thiết lập, hoạt động nhằm duy trì sự cai trị và khai thác tài nguyên tại Việt Nam, thường xuyên phải đối mặt với các cuộc kháng chiến của nhân dân."<SEP>"Chính quyền thực dân tại Đông Dương là lực lượng cai trị, phản động nghịch lại các yêu cầu dân chủ và dân sinh, đã thực hiện nhiều biện pháp hạn chế quyền tự do của người dân, trong đó có việc cấm các cuộc hội họp, mít tinh của quần chúng."', 'entity_name': '"HỘI LIÊN HIỆP THUỘC ĐỊA"', 'id': 'ent-3876555f55fca0145139e2a168b46f81', 'distance': 0.49185094237327576, 'entity_description': '"Tổ chức được thành lập để tập hợp các dân tộc thuộc địa chống lại thực dân."', 'entity_name': '"BỘ CHÍNH TRỊ BAN CHẤP HÀNH TRUNG ƯƠNG ĐẢNG"', 'id': 'ent-ae73daa6bf1faea0a20d348029e83d79', 'distance': 0.4911544620990753, 'entity_description': '"Bộ Chính trị Ban Chấp hành Trung ương Đảng Cộng sản Việt Nam là cơ quan lãnh đạo cao nhất, đã họp ở Việt Bắc để bàn về kế hoạch quân sự trong mùa đông - xuân 1953-1954, với mục tiêu chủ yếu là tiêu diệt địch."', 'entity_name': '"VIỆT MINH"', 'id': 'ent-4d0c1267a968719728d4a809c8d5547e', 'distance': 0.4911538362503052, 'entity_description': 'Việt Minh là một tổ chức chính trị-militar được thành lập để lãnh đạo phong trào kháng chiến tại Việt Nam, có vai trò quan trọng trong việc tổ chức và lãnh đạo quần chúng nhân dân chống lại sự chiếm đóng của thực dân Pháp và phát xít Nhật. Dưới sự lãnh đạo của Đảng Cộng sản, Việt Minh đã tập hợp nhiều lực lượng yêu nước và tiến bộ xã hội, nhằm mục tiêu giành độc lập cho đất nước và giải phóng dân tộc.\n\nVietnamese revolutionary organization, Việt Minh, was established to unite the Vietnamese people in their struggle for independence and to protect the nation during the occupation of French colonialists and Japanese fascists. The organization played a crucial role in the success of the August Revolution in 1945, significantly contributing to the effectiveness of the national liberation movement. Việt Minh không chỉ là tổ chức chính trị - quân sự mà còn là biểu tượng cho lòng yêu nước của nhân dân Việt Nam trong cuộc chiến giành độc lập và tự do.', 'entity_name': '"ĐẠI VIỆT"', 'id': 'ent-a564db4bc86b429cf66757223505803f', 'distance': 0.4911462962627411, 'entity_description': '"Đại Việt là một trong những đảng phái chính trị tại Đông Dương, thân Nhật, đã hoạt động trong bối cảnh Nhật Bản xâm chiếm khu vực và có những hoạt động tuyên truyền nhằm lật đổ thực dân Pháp."', 'entity_name': '"VIỆT NAM CÁCH MẠNG ĐỒNG MINH HỘI"', 'id': 'ent-7ab4861b505f26a1f4b8613455c79bee', 'distance': 0.4902685284614563, 'entity_description': '"Việt Nam Cách mạng đồng minh hội là một tổ chức phản động có ý đồ cướp chính quyền, với sự hỗ trợ từ quân đội Trung Hoa Dân quốc và thực dân Pháp."', 'entity_name': '"PHONG TRÀO DÂN CHỦ"', 'id': 'ent-1b3b5f1b0d75c0fec84825ebab86865c', 'distance': 0.4897870719432831, 'entity_description': '"Phong trào dân chủ là sự kiện diễn ra từ giữa năm 1936 đến 1939, khi người dân Việt Nam dưới sự lãnh đạo của Đảng Cộng sản đã tham gia vào các cuộc đấu tranh nhằm đòi tự do và dân chủ, chống lại chính quyền thực dân. Đây là giai đoạn quan trọng đánh dấu sự gia tăng ý thức đấu tranh của nhân dân."', 'entity_name': '"ĐẠI HỘI ĐÔNG DƯƠNG"', 'id': 'ent-29436d7439214f193316ac390918a62a', 'distance': 0.48934826254844666, 'entity_description': '"Đại hội Đông Dương được triệu tập nhằm thảo luận và thúc đẩy các yêu cầu về tự do, dân chủ. Tuy nhiên, sự kiện này đã bị cấm hoạt động bởi chính quyền thực dân."', 'entity_name': '"LIÊN MINH CÁC LỰC LƯỢNG DÂN TỘC, DÂN CHỦ VÀ HOÀ BÌNH"', 'id': 'ent-7807e28d813b32f35c8bd4a2fa481b1a', 'distance': 0.4847652018070221, 'entity_description': '"Tổ chức Liên minh các lực lượng dân tộc, dân chủ và hoà bình được thành lập để đại diện cho các tầng lớp trí thức, tư sản dân tộc tiến bộ ở các thành thị trong cuộc chiến chống Mỹ, thể hiện sự đoàn kết và đấu tranh giành độc lập của người dân Việt Nam."', 'id': 'ent-71318cdf16440613d8f5e1fe86b6ea14', 'entity_name': '"HỘI NGHỊ BAN CHẤP HÀNH TRUNG ƯƠNG ĐẢNG CỘNG SẢN ĐÔNG DƯƠNG THÁNG 7 – 1936"', 'entity_time': datetime.datetime(1936, 7, 1, 0, 0), 'entity_description': '"Hội nghị này có ý nghĩa quan trọng trong việc xác định đường lối đấu tranh của Đảng Cộng sản Đông Dương, với mục tiêu chống đế quốc, chống phong kiến, và đòi hỏi các quyền tự do, dân sinh, dân chủ cho nhân dân. Hội nghị quyết định thành lập Mặt trận Thống nhất nhân dân phản đế Đông Dương và kêu gọi các đảng phái cùng nhân dân tham gia phong trào đấu tranh."', 'distance': 0.5, 'id': 'ent-60322f4c787ed690440eea90c181044e', 'entity_name': '"MẶT TRẬN THỐNG NHẤT NHÂN DÂN PHẢN ĐẾ ĐÔNG DƯƠNG"', 'entity_time': datetime.datetime(1936, 1, 1, 0, 0), 'entity_description': '"Mặt trận này được thành lập nhằm tập hợp lực lượng chống lại thực dân Pháp và phong kiến. Nó khuyến khích sự đoàn kết giữa các tầng lớp xã hội để đấu tranh vì quyền lợi chung của nhân dân, góp phần xây dựng phong trào quần chúng mạnh mẽ hơn."', 'distance': 0.5, 'id': 'ent-bd71e5e1e81d6661c8453c3cdeb3e068', 'entity_name': '"MÁTXCƠVA"', 'entity_time': datetime.datetime(1935, 7, 1, 0, 0), 'entity_description': '"Mátxcơva là nơi tổ chức Đại hội lần thứ VII của Quốc tế Cộng sản, nơi Đảng Cộng sản Đông Dương đã tham gia để xác định kẻ thù là chủ nghĩa phát xít và nhiệm vụ của giai cấp công nhân trong giai đoạn mới."', 'distance': 0.5, 'id': 'ent-0bd1c17e14e9d8946b0a56fdff462693', 'entity_name': '"CHÍNH PHỦ MẶT TRẬN NHÂN DÂN"', 'entity_time': datetime.datetime(1936, 6, 1, 0, 0), 'entity_description': '"Chính phủ Mặt trận Nhân dân là chính phủ mới ở Pháp, lên cầm quyền và thực hiện nhiều chính sách tiến bộ ở thuộc địa, tạo ra cơ hội cho các phong trào cách mạng ở Đông Dương phát triển."', 'distance': 0.5]
Kết quả:
PHONG TRÀO DÂN CHỦ 1936 – 1939|HỘI NGHỊ BAN CHẤP HÀNH TRUNG ƯƠNG ĐẢNG CỘNG SẢN ĐÔNG DƯƠNG THÁNG 7 – 1936|THÁNG 9 - 1936|ĐẠI HỘI ĐÔNG DƯƠNG|MẶT TRẬN THỐNG NHẤT NHÂN DÂN PHẢN ĐẾ ĐÔNG DƯƠNG|CHÍNH PHỦ MẶT TRẬN NHÂN DÂN|ĐẢNG CỘNG SẢN|ĐẢNG CỘNG SẢN VIỆT NAM|MÁTXCƠVA|CHÍNH QUYỀN THỰC DÂN
###################### Dữ liệu thực tế ######################
Câu hỏi:
    {query}
Danh sách các thực thể:
    {str(results)}
######################
Output:
    """
        rerank_entities = await gpt_4o_complete(rerank_entity_query)
        rerank_entities_list = rerank_entities.split("|")
        # rerank_entities_list=[entity.replace('"','') for entity in rerank_entities_list]
        # temp_results = []
        # print(results)
        # for entity in results:
        #     if entity['entity_name'][1:-2] in rerank_entities_list:
        #         temp_results.append(entity)
        # results = temp_results
        results = [entity for entity in results if entity['entity_name'] in rerank_entities_list]
    except:
        print("Can't do rerank for query output")

    if not len(results):
        return None
    node_datas = await asyncio.gather(
        *[knowledge_graph_inst.get_node(r["entity_name"]) for r in results]
    )
    if not all([n is not None for n in node_datas]):
        logger.warning("Some nodes are missing, maybe the storage is damaged")
    node_degrees = await asyncio.gather(
        *[knowledge_graph_inst.node_degree(r["entity_name"]) for r in results]
    )
    node_datas = [
        {**n, "entity_name": k["entity_name"], "rank": d}
        for k, n, d in zip(results, node_datas, node_degrees)
        if n is not None
    ]
    # use_communities = await _find_most_related_community_from_entities(
    #     node_datas, query_param, community_reports
    # )
    use_text_units = await _find_most_related_text_unit_from_entities(
        node_datas, query_param, text_chunks_db, knowledge_graph_inst
    )
    use_relations = await _find_most_related_edges_from_entities(
        node_datas, query_param, knowledge_graph_inst
    )
    # logger.info(
    #     f"Using {len(node_datas)} entites, {len(use_communities)} communities, {len(use_relations)} relations, {len(use_text_units)} text units"
    # )
    entites_section_list = [["id", "entity", "type", "description", "rank"]]
    for i, n in enumerate(node_datas):
        entites_section_list.append(
            [
                i,
                n["entity_name"],
                n.get("entity_type", "UNKNOWN"),
                n.get("description", "UNKNOWN"),
                n["rank"],
            ]
        )
    entities_context = list_of_list_to_csv(entites_section_list)

    relations_section_list = [
        ["id", "source", "target", "description", "weight", "rank"]
    ]
    for i, e in enumerate(use_relations):
        relations_section_list.append(
            [
                i,
                e["src_tgt"][0],
                e["src_tgt"][1],
                e["description"],
                e["weight"],
                e["rank"],
            ]
        )
    relations_context = list_of_list_to_csv(relations_section_list)

    communities_section_list = [["id", "content"]]
    # for i, c in enumerate(use_communities):
    #     communities_section_list.append([i, c["report_string"]])
    communities_context = list_of_list_to_csv(communities_section_list)

    text_units_section_list = [["id", "content"]]
    for i, t in enumerate(use_text_units):
        text_units_section_list.append([i, t["content"]])
    text_units_context = list_of_list_to_csv(text_units_section_list)
    return f"""
-----Entities-----
```csv
{entities_context}
```
-----Sources-----
```csv
{text_units_context}
```
"""


async def local_query(
    query,
    knowledge_graph_inst: BaseGraphStorage,
    entities_vdb: BaseVectorStorage,
    community_reports: BaseKVStorage[CommunitySchema],
    text_chunks_db: BaseKVStorage[TextChunkSchema],
    query_param: QueryParam,
    global_config: dict,
) -> str:
    from ._llm import gpt_4o_mini_complete
    use_model_func = global_config["cheap_model_func"]

    filter_query = f"""
Dưới đây là 1 câu hỏi trắc nghiệm về chủ đề lịch sử, bạn có thể giúp tôi lọc bỏ những đáp án chắc chắn sai và giữ lại những đáp án có khả năng là đáp án chính xác.
Các đáp án có khả năng trên sẽ được tìm kiếm trên bộ dữ liệu để xác định kết quả chính xác nhất.
Đầu ra chỉ cần là câu hỏi cũ và các đáp án có thể có. Không cần giải thích gì thêm
###################### Ví dụ ######################
Input:
Cách mạng tháng Tám năm 1945 và cuộc Tổng tiến công và nổi dậy Xuân 1975 ở Việt Nam có điểm chung là  
A. xóa bỏ được tình trạng đất nước bị chia cắt.  
B. hoàn thành cuộc cách mạng dân chủ nhân dân.  
C. hoàn thành thống nhất đất nước về mặt nhà nước.  
D. được sự ủng hộ mạnh mẽ của nhân dân thế giới.
Output:
Cách mạng tháng Tám năm 1945 và cuộc Tổng tiến công và nổi dậy Xuân 1975 ở Việt Nam có điểm chung là  
A. xóa bỏ được tình trạng đất nước bị chia cắt.  
C. hoàn thành thống nhất đất nước về mặt nhà nước.  
###################### Dữ liệu thực tế ######################
Input: {query}
    """
    query = await use_model_func(filter_query)
    print(query)

    context = await _build_local_query_context(
        query,
        knowledge_graph_inst,
        entities_vdb,
        community_reports,
        text_chunks_db,
        query_param,
    )
    if query_param.only_need_context:
        print(f"@@@@@@@@@@@@@@@@@@@\nContext below:\n{context}")
    if context is None:
        return PROMPTS["fail_response"]
    sys_prompt_temp = PROMPTS["local_rag_response"]
    sys_prompt = sys_prompt_temp.format(
        context_data=context, response_type=query_param.response_type
    )

    final_query = f"""
Bạn là một trợ lý AI chuyên gia về trả lời câu hỏi trắc nghiệm. Hãy đọc kỹ câu hỏi sau và chỉ trả lời bằng một ký tự đại diện cho đáp án đúng (A, B, C, D). Không giải thích, không đưa thêm thông tin, chỉ trả về một ký tự duy nhất:
Câu hỏi:
{query}
Định dạng đầu ra:
- Chỉ trả về một ký tự (A, B, C hoặc D)."""
    response = await use_model_func(
        final_query,
        system_prompt=sys_prompt,
    )
    return response


async def _map_global_communities(
    query: str,
    communities_data: list[CommunitySchema],
    query_param: QueryParam,
    global_config: dict,
):
    use_string_json_convert_func = global_config["convert_response_to_json_func"]
    use_model_func = global_config["best_model_func"]
    community_groups = []
    while len(communities_data):
        this_group = truncate_list_by_token_size(
            communities_data,
            key=lambda x: x["report_string"],
            max_token_size=query_param.global_max_token_for_community_report,
        )
        community_groups.append(this_group)
        communities_data = communities_data[len(this_group) :]

    async def _process(community_truncated_datas: list[CommunitySchema]) -> dict:
        communities_section_list = [["id", "content", "rating", "importance"]]
        for i, c in enumerate(community_truncated_datas):
            communities_section_list.append(
                [
                    i,
                    c["report_string"],
                    c["report_json"].get("rating", 0),
                    c["occurrence"],
                ]
            )
        community_context = list_of_list_to_csv(communities_section_list)
        sys_prompt_temp = PROMPTS["global_map_rag_points"]
        sys_prompt = sys_prompt_temp.format(context_data=community_context)
        response = await use_model_func(
            query,
            system_prompt=sys_prompt,
            **query_param.global_special_community_map_llm_kwargs,
        )
        data = use_string_json_convert_func(response)
        return data.get("points", [])

    logger.info(f"Grouping to {len(community_groups)} groups for global search")
    responses = await asyncio.gather(*[_process(c) for c in community_groups])
    return responses


async def global_query(
    query,
    knowledge_graph_inst: BaseGraphStorage,
    entities_vdb: BaseVectorStorage,
    community_reports: BaseKVStorage[CommunitySchema],
    text_chunks_db: BaseKVStorage[TextChunkSchema],
    query_param: QueryParam,
    global_config: dict,
) -> str:
    community_schema = await knowledge_graph_inst.community_schema()
    community_schema = {
        k: v for k, v in community_schema.items() if v["level"] <= query_param.level
    }
    if not len(community_schema):
        return PROMPTS["fail_response"]
    use_model_func = global_config["best_model_func"]

    sorted_community_schemas = sorted(
        community_schema.items(),
        key=lambda x: x[1]["occurrence"],
        reverse=True,
    )
    sorted_community_schemas = sorted_community_schemas[
        : query_param.global_max_consider_community
    ]
    community_datas = await community_reports.get_by_ids(
        [k[0] for k in sorted_community_schemas]
    )
    community_datas = [c for c in community_datas if c is not None]
    community_datas = [
        c
        for c in community_datas
        if c["report_json"].get("rating", 0) >= query_param.global_min_community_rating
    ]
    community_datas = sorted(
        community_datas,
        key=lambda x: (x["occurrence"], x["report_json"].get("rating", 0)),
        reverse=True,
    )
    logger.info(f"Revtrieved {len(community_datas)} communities")

    map_communities_points = await _map_global_communities(
        query, community_datas, query_param, global_config
    )
    final_support_points = []
    for i, mc in enumerate(map_communities_points):
        for point in mc:
            if "description" not in point:
                continue
            final_support_points.append(
                {
                    "analyst": i,
                    "answer": point["description"],
                    "score": point.get("score", 1),
                }
            )
    final_support_points = [p for p in final_support_points if p["score"] > 0]
    if not len(final_support_points):
        return PROMPTS["fail_response"]
    final_support_points = sorted(
        final_support_points, key=lambda x: x["score"], reverse=True
    )
    final_support_points = truncate_list_by_token_size(
        final_support_points,
        key=lambda x: x["answer"],
        max_token_size=query_param.global_max_token_for_community_report,
    )
    points_context = []
    for dp in final_support_points:
        points_context.append(
            f"""----Analyst {dp['analyst']}----
Importance Score: {dp['score']}
{dp['answer']}
"""
        )
    points_context = "\n".join(points_context)
    if query_param.only_need_context:
        return points_context
    sys_prompt_temp = PROMPTS["global_reduce_rag_response"]
    response = await use_model_func(
        query,
        sys_prompt_temp.format(
            report_data=points_context, response_type=query_param.response_type
        ),
    )
    return response


async def naive_query(
    query,
    chunks_vdb: BaseVectorStorage,
    text_chunks_db: BaseKVStorage[TextChunkSchema],
    query_param: QueryParam,
    global_config: dict,
):
    use_model_func = global_config["best_model_func"]
    results = await chunks_vdb.query(query, top_k=query_param.top_k)
    if not len(results):
        return PROMPTS["fail_response"]
    chunks_ids = [r["id"] for r in results]
    chunks = await text_chunks_db.get_by_ids(chunks_ids)

    maybe_trun_chunks = truncate_list_by_token_size(
        chunks,
        key=lambda x: x["content"],
        max_token_size=query_param.naive_max_token_for_text_unit,
    )
    logger.info(f"Truncate {len(chunks)} to {len(maybe_trun_chunks)} chunks")
    section = "--New Chunk--\n".join([c["content"] for c in maybe_trun_chunks])
    if query_param.only_need_context:
        return section
    sys_prompt_temp = PROMPTS["naive_rag_response"]
    sys_prompt = sys_prompt_temp.format(
        content_data=section, response_type=query_param.response_type
    )
    response = await use_model_func(
        query,
        system_prompt=sys_prompt,
    )
    return response

