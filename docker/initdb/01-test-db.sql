-- Creates the separate database used by the automated test suite.
SELECT 'CREATE DATABASE warranty_test' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'warranty_test')\gexec
