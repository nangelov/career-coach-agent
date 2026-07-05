(.venv) nangelov@Lenovo-Angelovi:~/ws/hf-github/career-coach-agent/backend/tests$ uv run --no-sync pytest
warning: `VIRTUAL_ENV=/home/nangelov/ws/hf-github/career-coach-agent/.venv` does not match the project environment path `/home/nangelov/ws/hf-github/career-coach-agent/backend/.venv` and will be ignored; use `--active` to target the active environment instead
========================================================================================= test session starts ==========================================================================================
platform linux -- Python 3.11.15, pytest-9.1.1, pluggy-1.6.0
rootdir: /home/nangelov/ws/hf-github/career-coach-agent/backend
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 142 items                                                                                                                                                                                    

test_chat_api.py ..                                                                                                                                                                              [  1%]
test_chat_cancel.py ...........                                                                                                                                                                  [  9%]
test_chat_persistence.py .........                                                                                                                                                               [ 15%]
test_chat_service.py .....                                                                                                                                                                       [ 19%]
test_conversation_store.py ssss                                                                                                                                                                  [ 21%]
test_embeddings.py ..........                                                                                                                                                                    [ 28%]
test_health.py .                                                                                                                                                                                 [ 29%]
test_identity_models.py ssssss                                                                                                                                                                   [ 33%]
test_knowledge_models.py sssssssss                                                                                                                                                               [ 40%]
test_llm_client.py ....                                                                                                                                                                          [ 42%]
test_llm_router.py ..........                                                                                                                                                                    [ 50%]
test_message_id.py .........                                                                                                                                                                     [ 56%]
test_p2_exit_verification.py sssss                                                                                                                                                               [ 59%]
test_postgres_repository.py ............                                                                                                                                                         [ 68%]
test_session_memory.py ..........                                                                                                                                                                [ 75%]
test_structured_models.py ssssssssss                                                                                                                                                             [ 82%]
test_tools.py ...................                                                                                                                                                                [ 95%]
test_vector_search.py ssssss                                                                                                                                                                     [100%]

=================================================================================== 102 passed, 40 skipped in 6.36s ====================================================================================
(.venv) nangelov@Lenovo-Angelovi:~/ws/hf-github/career-coach-agent/backend/tests$ 