-- The API can enqueue jobs and the worker can run them. Nobody else touches this schema.
GRANT USAGE ON SCHEMA jobs TO astra_api, astra_worker;
GRANT ALL ON ALL TABLES IN SCHEMA jobs TO astra_api, astra_worker;
GRANT ALL ON ALL SEQUENCES IN SCHEMA jobs TO astra_api, astra_worker;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA jobs TO astra_api, astra_worker;
