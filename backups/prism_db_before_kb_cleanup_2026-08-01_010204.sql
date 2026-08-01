-- MySQL dump 10.13  Distrib 8.0.46, for Linux (x86_64)
--
-- Host: localhost    Database: prism_db
-- ------------------------------------------------------
-- Server version	8.0.46

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `agent_trace`
--

DROP TABLE IF EXISTS `agent_trace`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `agent_trace` (
  `id` char(36) NOT NULL,
  `session_id` char(36) DEFAULT NULL,
  `user_message_id` char(36) DEFAULT NULL,
  `assistant_message_id` char(36) DEFAULT NULL,
  `user_query` text,
  `status` varchar(32) DEFAULT NULL,
  `model` varchar(128) DEFAULT NULL,
  `started_at` datetime DEFAULT NULL,
  `ended_at` datetime DEFAULT NULL,
  `trace_json` json DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_agent_trace_assistant_message` (`assistant_message_id`),
  KEY `ix_agent_trace_assistant_message_id` (`assistant_message_id`),
  KEY `ix_agent_trace_user_message_id` (`user_message_id`),
  KEY `ix_agent_trace_session_id` (`session_id`),
  KEY `ix_agent_trace_status` (`status`),
  KEY `ix_agent_trace_session_started` (`session_id`,`started_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `agent_trace`
--

LOCK TABLES `agent_trace` WRITE;
/*!40000 ALTER TABLE `agent_trace` DISABLE KEYS */;
INSERT INTO `agent_trace` VALUES ('7628be4c-d025-4c89-9225-b94d353a27ad','91a19cc1-9d88-4d3d-9385-24b16ac4d573','5fbb085b-961c-4ba8-a111-7d2a5d897077','860daf4b-9ef3-4660-9118-573ce1c68a91','你好','success','deepseek-v4-flash','2026-08-01 00:45:42','2026-08-01 00:45:47',NULL);
/*!40000 ALTER TABLE `agent_trace` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `agent_trace_evidence`
--

DROP TABLE IF EXISTS `agent_trace_evidence`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `agent_trace_evidence` (
  `id` char(36) NOT NULL,
  `trace_step_id` char(36) NOT NULL,
  `evidence_id` varchar(255) NOT NULL,
  `source_kind` varchar(64) DEFAULT NULL,
  `source_id` varchar(128) DEFAULT NULL,
  `chunk_id` varchar(128) DEFAULT NULL,
  `parent_chunk_id` varchar(128) DEFAULT NULL,
  `item_id` varchar(128) DEFAULT NULL,
  `display_title` varchar(512) DEFAULT NULL,
  `excerpt` text,
  `hit_reason` text,
  `score` float DEFAULT NULL,
  `retrieval_path_json` json DEFAULT NULL,
  `metadata_json` json DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_agent_trace_evidence_trace_step_id` (`trace_step_id`),
  KEY `ix_agent_trace_evidence_source_id` (`source_id`),
  KEY `ix_agent_trace_evidence_chunk_id` (`chunk_id`),
  KEY `ix_agent_trace_evidence_evidence_id` (`evidence_id`),
  KEY `ix_agent_trace_evidence_item_id` (`item_id`),
  KEY `ix_agent_trace_evidence_source_kind` (`source_kind`),
  KEY `ix_agent_trace_evidence_chunk` (`chunk_id`),
  KEY `ix_agent_trace_evidence_source` (`source_kind`,`source_id`),
  CONSTRAINT `agent_trace_evidence_ibfk_1` FOREIGN KEY (`trace_step_id`) REFERENCES `agent_trace_step` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `agent_trace_evidence`
--

LOCK TABLES `agent_trace_evidence` WRITE;
/*!40000 ALTER TABLE `agent_trace_evidence` DISABLE KEYS */;
/*!40000 ALTER TABLE `agent_trace_evidence` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `agent_trace_step`
--

DROP TABLE IF EXISTS `agent_trace_step`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `agent_trace_step` (
  `id` char(36) NOT NULL,
  `trace_id` char(36) NOT NULL,
  `step_index` int NOT NULL,
  `step_type` varchar(64) NOT NULL,
  `tool_name` varchar(128) DEFAULT NULL,
  `tool_call_id` varchar(128) DEFAULT NULL,
  `input_json` json DEFAULT NULL,
  `output_json` json DEFAULT NULL,
  `status` varchar(32) DEFAULT NULL,
  `latency_ms` int DEFAULT NULL,
  `started_at` datetime DEFAULT NULL,
  `ended_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_agent_trace_step_step_type` (`step_type`),
  KEY `ix_agent_trace_step_trace_id` (`trace_id`),
  KEY `ix_agent_trace_step_trace_index` (`trace_id`,`step_index`),
  KEY `ix_agent_trace_step_tool_call` (`tool_call_id`),
  KEY `ix_agent_trace_step_status` (`status`),
  CONSTRAINT `agent_trace_step_ibfk_1` FOREIGN KEY (`trace_id`) REFERENCES `agent_trace` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `agent_trace_step`
--

LOCK TABLES `agent_trace_step` WRITE;
/*!40000 ALTER TABLE `agent_trace_step` DISABLE KEYS */;
INSERT INTO `agent_trace_step` VALUES ('11ebabdf-95c8-4415-ad37-f18155790e25','7628be4c-d025-4c89-9225-b94d353a27ad',1,'model_response',NULL,NULL,'{\"iteration\": 1}','{\"iteration\": 1, \"tool_calls\": [], \"content_preview\": \"你好！我是 Prism，你的个人知识管理助理。我可以帮你：\\n\\n- **检索**知识库中的内容，比如某个观点、事实或原文片段\\n- **整理**和**总结**你的笔记、文档与长期记忆\\n- **追溯**信息来源，给出带出处的可靠回答\\n\\n你可以直接问我问题，比如“帮我找找关于 XX 的笔记”，或者告诉我你正在关注的主题。有什么需要帮忙的吗？\"}','success',NULL,'2026-08-01 00:45:45','2026-08-01 00:45:45'),('9f686c99-92da-4319-8011-55fd750a5f89','7628be4c-d025-4c89-9225-b94d353a27ad',0,'model_invoke',NULL,NULL,'{\"iteration\": 1, \"message_count\": 2, \"message_roles\": [\"system\", \"human\"], \"effective_objective_source\": \"current\"}','null','success',NULL,'2026-08-01 00:45:43','2026-08-01 00:45:43'),('b9a98f5f-f929-4599-baff-cffc8cbbbf64','7628be4c-d025-4c89-9225-b94d353a27ad',2,'final_answer',NULL,NULL,'null','{\"content\": \"你好！我是 Prism，你的个人知识管理助理。我可以帮你：\\n\\n- **检索**知识库中的内容，比如某个观点、事实或原文片段\\n- **整理**和**总结**你的笔记、文档与长期记忆\\n- **追溯**信息来源，给出带出处的可靠回答\\n\\n你可以直接问我问题，比如“帮我找找关于 XX 的笔记”，或者告诉我你正在关注的主题。有什么需要帮忙的吗？\"}','success',NULL,'2026-08-01 00:45:47','2026-08-01 00:45:47');
/*!40000 ALTER TABLE `agent_trace_step` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `asset_relation`
--

DROP TABLE IF EXISTS `asset_relation`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `asset_relation` (
  `id` char(36) NOT NULL,
  `user_id` char(36) NOT NULL,
  `from_asset_id` char(36) NOT NULL,
  `to_asset_id` char(36) NOT NULL,
  `relation_type` varchar(64) DEFAULT NULL,
  `reason` text,
  `confidence` float DEFAULT NULL,
  `source_draft_id` char(36) DEFAULT NULL,
  `status` varchar(32) DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `from_asset_id` (`from_asset_id`),
  KEY `to_asset_id` (`to_asset_id`),
  KEY `ix_asset_relation_user_id` (`user_id`),
  KEY `ix_asset_relation_relation_type` (`relation_type`),
  KEY `ix_asset_relation_status` (`status`),
  CONSTRAINT `asset_relation_ibfk_1` FOREIGN KEY (`from_asset_id`) REFERENCES `personal_asset_item` (`id`) ON DELETE CASCADE,
  CONSTRAINT `asset_relation_ibfk_2` FOREIGN KEY (`to_asset_id`) REFERENCES `personal_asset_item` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `asset_relation`
--

LOCK TABLES `asset_relation` WRITE;
/*!40000 ALTER TABLE `asset_relation` DISABLE KEYS */;
/*!40000 ALTER TABLE `asset_relation` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `asset_usage_event`
--

DROP TABLE IF EXISTS `asset_usage_event`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `asset_usage_event` (
  `id` char(36) NOT NULL,
  `user_id` char(36) NOT NULL,
  `session_id` char(36) DEFAULT NULL,
  `message_id` char(36) DEFAULT NULL,
  `asset_id` char(36) NOT NULL,
  `usage_type` varchar(64) DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `asset_id` (`asset_id`),
  KEY `ix_asset_usage_event_session_id` (`session_id`),
  KEY `ix_asset_usage_event_user_id` (`user_id`),
  KEY `ix_asset_usage_event_usage_type` (`usage_type`),
  KEY `ix_asset_usage_event_message_id` (`message_id`),
  CONSTRAINT `asset_usage_event_ibfk_1` FOREIGN KEY (`asset_id`) REFERENCES `personal_asset_item` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `asset_usage_event`
--

LOCK TABLES `asset_usage_event` WRITE;
/*!40000 ALTER TABLE `asset_usage_event` DISABLE KEYS */;
/*!40000 ALTER TABLE `asset_usage_event` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `canonical_knowledge_point`
--

DROP TABLE IF EXISTS `canonical_knowledge_point`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `canonical_knowledge_point` (
  `id` char(36) NOT NULL,
  `user_id` char(36) NOT NULL,
  `canonical_type` varchar(64) DEFAULT NULL,
  `title` varchar(255) NOT NULL,
  `canonical_statement` text NOT NULL,
  `summary` text,
  `aliases` json DEFAULT NULL,
  `domains` json DEFAULT NULL,
  `entities` json DEFAULT NULL,
  `concepts` json DEFAULT NULL,
  `keywords` json DEFAULT NULL,
  `scope` json DEFAULT NULL,
  `conditions` json DEFAULT NULL,
  `status` varchar(32) DEFAULT NULL COMMENT 'draft/stable/disputed/deprecated',
  `confidence` float DEFAULT NULL,
  `embedding_ref` varchar(255) DEFAULT NULL,
  `embedding_model` varchar(128) DEFAULT NULL,
  `embedding_status` varchar(32) DEFAULT NULL,
  `metadata` json DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_canonical_knowledge_point_embedding_status` (`embedding_status`),
  KEY `ix_canonical_knowledge_point_user_id` (`user_id`),
  KEY `ix_canonical_knowledge_point_status` (`status`),
  KEY `ix_ckp_title` (`title`),
  KEY `ix_canonical_knowledge_point_canonical_type` (`canonical_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `canonical_knowledge_point`
--

LOCK TABLES `canonical_knowledge_point` WRITE;
/*!40000 ALTER TABLE `canonical_knowledge_point` DISABLE KEYS */;
/*!40000 ALTER TABLE `canonical_knowledge_point` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `canonical_relation`
--

DROP TABLE IF EXISTS `canonical_relation`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `canonical_relation` (
  `id` char(36) NOT NULL,
  `user_id` char(36) NOT NULL,
  `source_canonical_id` char(36) NOT NULL,
  `target_canonical_id` char(36) NOT NULL,
  `relation_type` varchar(64) DEFAULT NULL,
  `confidence` float DEFAULT NULL,
  `reason` text,
  `metadata` json DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_ckp_relation` (`source_canonical_id`,`target_canonical_id`,`relation_type`),
  KEY `ix_canonical_relation_relation_type` (`relation_type`),
  KEY `ix_canonical_relation_user_id` (`user_id`),
  KEY `ix_canonical_relation_target_canonical_id` (`target_canonical_id`),
  KEY `ix_canonical_relation_source_canonical_id` (`source_canonical_id`),
  CONSTRAINT `canonical_relation_ibfk_1` FOREIGN KEY (`source_canonical_id`) REFERENCES `canonical_knowledge_point` (`id`) ON DELETE CASCADE,
  CONSTRAINT `canonical_relation_ibfk_2` FOREIGN KEY (`target_canonical_id`) REFERENCES `canonical_knowledge_point` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `canonical_relation`
--

LOCK TABLES `canonical_relation` WRITE;
/*!40000 ALTER TABLE `canonical_relation` DISABLE KEYS */;
/*!40000 ALTER TABLE `canonical_relation` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `chat_message`
--

DROP TABLE IF EXISTS `chat_message`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `chat_message` (
  `id` char(36) NOT NULL,
  `session_id` char(36) NOT NULL,
  `role` varchar(20) NOT NULL COMMENT 'user/assistant/system',
  `content` text COMMENT '消息内容',
  `sources` json DEFAULT NULL COMMENT '引用的知识块ID列表',
  `clarify` json DEFAULT NULL COMMENT '追问卡片数据',
  `process` json DEFAULT NULL COMMENT 'assistant process state',
  `created_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `session_id` (`session_id`),
  CONSTRAINT `chat_message_ibfk_1` FOREIGN KEY (`session_id`) REFERENCES `chat_session` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `chat_message`
--

LOCK TABLES `chat_message` WRITE;
/*!40000 ALTER TABLE `chat_message` DISABLE KEYS */;
INSERT INTO `chat_message` VALUES ('5fbb085b-961c-4ba8-a111-7d2a5d897077','91a19cc1-9d88-4d3d-9385-24b16ac4d573','user','你好','null','null','null','2026-08-01 00:45:41'),('860daf4b-9ef3-4660-9118-573ce1c68a91','91a19cc1-9d88-4d3d-9385-24b16ac4d573','assistant','你好！我是 Prism，你的个人知识管理助理。我可以帮你：\n\n- **检索**知识库中的内容，比如某个观点、事实或原文片段\n- **整理**和**总结**你的笔记、文档与长期记忆\n- **追溯**信息来源，给出带出处的可靠回答\n\n你可以直接问我问题，比如“帮我找找关于 XX 的笔记”，或者告诉我你正在关注的主题。有什么需要帮忙的吗？','null','null','{\"trace_id\": \"7628be4c-d025-4c89-9225-b94d353a27ad\", \"tool_runs\": [], \"agent_status\": \"generating answer\", \"thinking_steps\": [{\"tool\": \"agent_status\", \"label\": \"chat\", \"status\": \"success\", \"latencyMs\": 2428, \"startedAtMs\": 1785516341696}, {\"tool\": \"agent_status\", \"label\": \"generating answer\", \"status\": \"success\", \"latencyMs\": 2122, \"startedAtMs\": 1785516344124}], \"agent_continuation\": null}','2026-08-01 00:45:41');
/*!40000 ALTER TABLE `chat_message` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `chat_session`
--

DROP TABLE IF EXISTS `chat_session`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `chat_session` (
  `id` char(36) NOT NULL,
  `title` varchar(255) DEFAULT NULL COMMENT '会话标题',
  `user_id` char(36) DEFAULT NULL,
  `topic_id` char(36) DEFAULT NULL COMMENT '关联知识库主题',
  `source_types` json DEFAULT NULL COMMENT '过滤数据来源类型',
  `summary` text COMMENT 'LLM 生成的会话摘要',
  `last_extracted_message_id` char(36) DEFAULT NULL COMMENT '提取水位线：上次提取到的最后一条消息 ID',
  `last_extracted_at` datetime DEFAULT NULL COMMENT '上次触发提取的时间',
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `chat_session`
--

LOCK TABLES `chat_session` WRITE;
/*!40000 ALTER TABLE `chat_session` DISABLE KEYS */;
INSERT INTO `chat_session` VALUES ('91a19cc1-9d88-4d3d-9385-24b16ac4d573','Prism助理自我介绍','default-user','ecd1ea55-f9f5-5326-9187-327b3ec56661','null','','',NULL,'2026-08-01 00:45:41','2026-08-01 00:45:47');
/*!40000 ALTER TABLE `chat_session` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `entity_alias`
--

DROP TABLE IF EXISTS `entity_alias`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `entity_alias` (
  `id` char(36) NOT NULL,
  `entity_id` char(36) NOT NULL,
  `tenant_id` varchar(64) NOT NULL,
  `kb_uid` char(36) NOT NULL,
  `graph_generation` char(36) NOT NULL,
  `alias` varchar(512) NOT NULL,
  `normalized_key` varchar(512) NOT NULL,
  `confidence` float DEFAULT NULL,
  `extraction_method` varchar(128) DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_entity_alias_key` (`entity_id`,`normalized_key`),
  KEY `ix_entity_alias_graph_generation` (`graph_generation`),
  KEY `ix_entity_alias_normalized_key` (`normalized_key`),
  KEY `ix_entity_alias_lookup` (`normalized_key`),
  KEY `ix_entity_alias_tenant_id` (`tenant_id`),
  KEY `ix_entity_alias_scope` (`tenant_id`,`kb_uid`,`graph_generation`,`normalized_key`),
  KEY `ix_entity_alias_entity_id` (`entity_id`),
  KEY `ix_entity_alias_kb_uid` (`kb_uid`),
  CONSTRAINT `entity_alias_ibfk_1` FOREIGN KEY (`entity_id`) REFERENCES `knowledge_entity` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `entity_alias`
--

LOCK TABLES `entity_alias` WRITE;
/*!40000 ALTER TABLE `entity_alias` DISABLE KEYS */;
/*!40000 ALTER TABLE `entity_alias` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `entity_mention`
--

DROP TABLE IF EXISTS `entity_mention`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `entity_mention` (
  `id` char(36) NOT NULL,
  `entity_id` char(36) NOT NULL,
  `tenant_id` varchar(64) NOT NULL,
  `kb_uid` char(36) NOT NULL,
  `graph_generation` char(36) NOT NULL,
  `file_uid` char(36) NOT NULL,
  `chunk_uid` char(36) NOT NULL,
  `revision_id` char(36) NOT NULL,
  `active` varchar(8) NOT NULL,
  `char_start` int DEFAULT NULL,
  `char_end` int DEFAULT NULL,
  `source_kind` varchar(64) NOT NULL,
  `source_id` char(36) NOT NULL,
  `item_id` char(36) DEFAULT NULL,
  `chunk_id` char(36) DEFAULT NULL,
  `surface_text` varchar(512) NOT NULL,
  `normalized_key` varchar(512) NOT NULL,
  `evidence_span` text,
  `confidence` float DEFAULT NULL,
  `extraction_method` varchar(128) DEFAULT NULL,
  `metadata` json DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_entity_mention_source_surface` (`entity_id`,`source_kind`,`source_id`,`surface_text`),
  KEY `ix_entity_mention_chunk_id` (`chunk_id`),
  KEY `ix_entity_mention_tenant_id` (`tenant_id`),
  KEY `ix_entity_mention_graph_generation` (`graph_generation`),
  KEY `ix_entity_mention_chunk_uid` (`chunk_uid`),
  KEY `ix_entity_mention_entity_id` (`entity_id`),
  KEY `ix_entity_mention_revision_id` (`revision_id`),
  KEY `ix_entity_mention_source_id` (`source_id`),
  KEY `ix_entity_mention_source_kind` (`source_kind`),
  KEY `ix_entity_mention_normalized_key` (`normalized_key`),
  KEY `ix_entity_mention_file_uid` (`file_uid`),
  KEY `ix_entity_mention_item_id` (`item_id`),
  KEY `ix_entity_mention_source` (`source_kind`,`source_id`),
  KEY `ix_entity_mention_key` (`normalized_key`),
  KEY `ix_entity_mention_kb_uid` (`kb_uid`),
  KEY `ix_entity_mention_active` (`active`),
  CONSTRAINT `entity_mention_ibfk_1` FOREIGN KEY (`entity_id`) REFERENCES `knowledge_entity` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `entity_mention`
--

LOCK TABLES `entity_mention` WRITE;
/*!40000 ALTER TABLE `entity_mention` DISABLE KEYS */;
/*!40000 ALTER TABLE `entity_mention` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `entity_relation`
--

DROP TABLE IF EXISTS `entity_relation`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `entity_relation` (
  `id` char(36) NOT NULL,
  `subject_entity_id` char(36) NOT NULL,
  `tenant_id` varchar(64) NOT NULL,
  `kb_uid` char(36) NOT NULL,
  `graph_generation` char(36) NOT NULL,
  `file_uid` char(36) NOT NULL,
  `revision_id` char(36) NOT NULL,
  `active` varchar(8) NOT NULL,
  `predicate` varchar(128) NOT NULL,
  `object_entity_id` char(36) DEFAULT NULL,
  `object_literal` text,
  `relation_key` varchar(64) NOT NULL,
  `source_kind` varchar(64) NOT NULL,
  `source_id` char(36) NOT NULL,
  `evidence_span` text,
  `confidence` float DEFAULT NULL,
  `extraction_method` varchar(128) DEFAULT NULL,
  `metadata` json DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_entity_relation_evidence` (`relation_key`),
  KEY `ix_entity_relation_file_uid` (`file_uid`),
  KEY `ix_entity_relation_source_id` (`source_id`),
  KEY `ix_entity_relation_kb_uid` (`kb_uid`),
  KEY `ix_entity_relation_tenant_id` (`tenant_id`),
  KEY `ix_entity_relation_revision_id` (`revision_id`),
  KEY `ix_entity_relation_object_entity_id` (`object_entity_id`),
  KEY `ix_entity_relation_source_kind` (`source_kind`),
  KEY `ix_entity_relation_predicate` (`predicate`),
  KEY `ix_entity_relation_relation_key` (`relation_key`),
  KEY `ix_entity_relation_subject_entity_id` (`subject_entity_id`),
  KEY `ix_entity_relation_graph_generation` (`graph_generation`),
  KEY `ix_entity_relation_active` (`active`),
  CONSTRAINT `entity_relation_ibfk_1` FOREIGN KEY (`subject_entity_id`) REFERENCES `knowledge_entity` (`id`) ON DELETE CASCADE,
  CONSTRAINT `entity_relation_ibfk_2` FOREIGN KEY (`object_entity_id`) REFERENCES `knowledge_entity` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `entity_relation`
--

LOCK TABLES `entity_relation` WRITE;
/*!40000 ALTER TABLE `entity_relation` DISABLE KEYS */;
/*!40000 ALTER TABLE `entity_relation` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `evaluation_dataset`
--

DROP TABLE IF EXISTS `evaluation_dataset`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `evaluation_dataset` (
  `id` char(36) NOT NULL,
  `dataset_uid` char(36) NOT NULL,
  `tenant_id` char(36) NOT NULL,
  `kb_uid` char(36) NOT NULL,
  `name` varchar(255) NOT NULL,
  `created_by` char(36) NOT NULL,
  `source` varchar(32) NOT NULL,
  `metadata` json DEFAULT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_evaluation_dataset_uid` (`dataset_uid`),
  UNIQUE KEY `uq_evaluation_dataset_id_scope` (`id`,`tenant_id`,`kb_uid`),
  KEY `fk_evaluation_dataset_topic` (`kb_uid`),
  KEY `ix_evaluation_dataset_scope_created` (`tenant_id`,`kb_uid`,`created_at`),
  CONSTRAINT `fk_evaluation_dataset_topic` FOREIGN KEY (`kb_uid`) REFERENCES `knowledge_topic` (`kb_uid`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `evaluation_dataset`
--

LOCK TABLES `evaluation_dataset` WRITE;
/*!40000 ALTER TABLE `evaluation_dataset` DISABLE KEYS */;
/*!40000 ALTER TABLE `evaluation_dataset` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `evaluation_dataset_item`
--

DROP TABLE IF EXISTS `evaluation_dataset_item`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `evaluation_dataset_item` (
  `id` char(36) NOT NULL,
  `dataset_id` char(36) NOT NULL,
  `tenant_id` char(36) NOT NULL,
  `kb_uid` char(36) NOT NULL,
  `ordinal` int NOT NULL,
  `query` text NOT NULL,
  `gold_chunk_uids` json NOT NULL,
  `gold_answer` text,
  `metadata` json DEFAULT NULL,
  `created_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_evaluation_dataset_item_ordinal` (`dataset_id`,`ordinal`),
  UNIQUE KEY `uq_evaluation_dataset_item_id_scope` (`id`,`tenant_id`,`kb_uid`),
  KEY `fk_evaluation_dataset_item_parent_scope` (`dataset_id`,`tenant_id`,`kb_uid`),
  KEY `ix_evaluation_dataset_item_scope` (`tenant_id`,`kb_uid`,`dataset_id`),
  CONSTRAINT `fk_evaluation_dataset_item_parent_scope` FOREIGN KEY (`dataset_id`, `tenant_id`, `kb_uid`) REFERENCES `evaluation_dataset` (`id`, `tenant_id`, `kb_uid`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `evaluation_dataset_item`
--

LOCK TABLES `evaluation_dataset_item` WRITE;
/*!40000 ALTER TABLE `evaluation_dataset_item` DISABLE KEYS */;
/*!40000 ALTER TABLE `evaluation_dataset_item` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `evaluation_run`
--

DROP TABLE IF EXISTS `evaluation_run`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `evaluation_run` (
  `id` char(36) NOT NULL,
  `run_uid` char(36) NOT NULL,
  `dataset_id` char(36) NOT NULL,
  `tenant_id` char(36) NOT NULL,
  `kb_uid` char(36) NOT NULL,
  `created_by` char(36) NOT NULL,
  `model` varchar(255) DEFAULT NULL,
  `request_idempotency_key` varchar(128) NOT NULL,
  `request_fingerprint` char(64) NOT NULL,
  `config` json NOT NULL,
  `retrieval_config` json NOT NULL,
  `embedding_profile` json NOT NULL,
  `graph_config` json NOT NULL,
  `index_generation` char(36) DEFAULT NULL,
  `graph_generation` char(36) DEFAULT NULL,
  `status` varchar(32) NOT NULL,
  `progress_current` int NOT NULL,
  `progress_total` int NOT NULL,
  `metrics` json DEFAULT NULL,
  `cancel_requested_at` datetime DEFAULT NULL,
  `error_message` text,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_evaluation_run_uid` (`run_uid`),
  UNIQUE KEY `uq_evaluation_run_request_key` (`tenant_id`,`kb_uid`,`request_idempotency_key`),
  UNIQUE KEY `uq_evaluation_run_id_scope` (`id`,`tenant_id`,`kb_uid`),
  KEY `fk_evaluation_run_dataset_scope` (`dataset_id`,`tenant_id`,`kb_uid`),
  KEY `fk_evaluation_run_topic` (`kb_uid`),
  KEY `ix_evaluation_run_dataset` (`dataset_id`),
  KEY `ix_evaluation_run_scope_created` (`tenant_id`,`kb_uid`,`created_at`),
  CONSTRAINT `fk_evaluation_run_dataset_scope` FOREIGN KEY (`dataset_id`, `tenant_id`, `kb_uid`) REFERENCES `evaluation_dataset` (`id`, `tenant_id`, `kb_uid`) ON DELETE RESTRICT,
  CONSTRAINT `fk_evaluation_run_topic` FOREIGN KEY (`kb_uid`) REFERENCES `knowledge_topic` (`kb_uid`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `evaluation_run`
--

LOCK TABLES `evaluation_run` WRITE;
/*!40000 ALTER TABLE `evaluation_run` DISABLE KEYS */;
/*!40000 ALTER TABLE `evaluation_run` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `evaluation_run_item`
--

DROP TABLE IF EXISTS `evaluation_run_item`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `evaluation_run_item` (
  `id` char(36) NOT NULL,
  `run_id` char(36) NOT NULL,
  `dataset_item_id` char(36) DEFAULT NULL,
  `tenant_id` char(36) NOT NULL,
  `kb_uid` char(36) NOT NULL,
  `ordinal` int NOT NULL,
  `query` text NOT NULL,
  `gold_chunk_uids` json NOT NULL,
  `gold_answer` text,
  `status` varchar(32) NOT NULL,
  `evidence` json DEFAULT NULL,
  `metrics` json DEFAULT NULL,
  `error_message` text,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_evaluation_run_item_ordinal` (`run_id`,`ordinal`),
  KEY `fk_evaluation_run_item_parent_scope` (`run_id`,`tenant_id`,`kb_uid`),
  KEY `fk_evaluation_run_item_dataset_item_scope` (`dataset_item_id`,`tenant_id`,`kb_uid`),
  KEY `ix_evaluation_run_item_scope` (`tenant_id`,`kb_uid`,`run_id`),
  KEY `ix_evaluation_run_item_run_status` (`run_id`,`status`),
  CONSTRAINT `fk_evaluation_run_item_dataset_item_scope` FOREIGN KEY (`dataset_item_id`, `tenant_id`, `kb_uid`) REFERENCES `evaluation_dataset_item` (`id`, `tenant_id`, `kb_uid`) ON DELETE RESTRICT,
  CONSTRAINT `fk_evaluation_run_item_parent_scope` FOREIGN KEY (`run_id`, `tenant_id`, `kb_uid`) REFERENCES `evaluation_run` (`id`, `tenant_id`, `kb_uid`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `evaluation_run_item`
--

LOCK TABLES `evaluation_run_item` WRITE;
/*!40000 ALTER TABLE `evaluation_run_item` DISABLE KEYS */;
/*!40000 ALTER TABLE `evaluation_run_item` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `extension_point`
--

DROP TABLE IF EXISTS `extension_point`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `extension_point` (
  `id` char(36) NOT NULL,
  `user_id` char(36) NOT NULL,
  `asset_id` char(36) NOT NULL,
  `title` varchar(255) NOT NULL,
  `reason` text,
  `suggested_kind` varchar(64) DEFAULT NULL,
  `confidence` float DEFAULT NULL,
  `status` varchar(32) DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `asset_id` (`asset_id`),
  KEY `ix_extension_point_user_id` (`user_id`),
  KEY `ix_extension_point_status` (`status`),
  CONSTRAINT `extension_point_ibfk_1` FOREIGN KEY (`asset_id`) REFERENCES `personal_asset_item` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `extension_point`
--

LOCK TABLES `extension_point` WRITE;
/*!40000 ALTER TABLE `extension_point` DISABLE KEYS */;
/*!40000 ALTER TABLE `extension_point` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `graph_community`
--

DROP TABLE IF EXISTS `graph_community`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `graph_community` (
  `id` char(36) NOT NULL,
  `user_id` char(36) NOT NULL,
  `community_id` int NOT NULL,
  `label` varchar(64) DEFAULT NULL,
  `cohesion` float DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_graph_community_user_cid` (`user_id`,`community_id`),
  KEY `ix_graph_community_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `graph_community`
--

LOCK TABLES `graph_community` WRITE;
/*!40000 ALTER TABLE `graph_community` DISABLE KEYS */;
/*!40000 ALTER TABLE `graph_community` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `graph_extraction_revision`
--

DROP TABLE IF EXISTS `graph_extraction_revision`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `graph_extraction_revision` (
  `revision_id` char(36) NOT NULL,
  `tenant_id` varchar(64) NOT NULL,
  `kb_uid` char(36) NOT NULL,
  `file_uid` char(36) NOT NULL,
  `item_id` char(36) NOT NULL,
  `chunk_uid` char(36) NOT NULL,
  `graph_generation` char(36) NOT NULL,
  `content_hash` varchar(64) NOT NULL,
  `extractor_config_hash` varchar(64) NOT NULL,
  `status` varchar(24) NOT NULL,
  `model_version` varchar(255) NOT NULL,
  `prompt_version` varchar(128) NOT NULL,
  `created_at` datetime NOT NULL,
  PRIMARY KEY (`revision_id`),
  UNIQUE KEY `uq_graph_extraction_key` (`tenant_id`,`kb_uid`,`chunk_uid`,`content_hash`,`extractor_config_hash`),
  KEY `ix_graph_extraction_revision_chunk_uid` (`chunk_uid`),
  KEY `ix_graph_extraction_revision_file_uid` (`file_uid`),
  KEY `ix_graph_extraction_revision_graph_generation` (`graph_generation`),
  KEY `ix_graph_extraction_revision_tenant_id` (`tenant_id`),
  KEY `ix_graph_extraction_revision_item_id` (`item_id`),
  KEY `ix_graph_extraction_revision_kb_uid` (`kb_uid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `graph_extraction_revision`
--

LOCK TABLES `graph_extraction_revision` WRITE;
/*!40000 ALTER TABLE `graph_extraction_revision` DISABLE KEYS */;
/*!40000 ALTER TABLE `graph_extraction_revision` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `graph_insight_summary`
--

DROP TABLE IF EXISTS `graph_insight_summary`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `graph_insight_summary` (
  `id` char(36) NOT NULL,
  `user_id` char(36) NOT NULL,
  `suggested_questions` json DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_graph_insight_summary_user` (`user_id`),
  KEY `ix_graph_insight_summary_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `graph_insight_summary`
--

LOCK TABLES `graph_insight_summary` WRITE;
/*!40000 ALTER TABLE `graph_insight_summary` DISABLE KEYS */;
/*!40000 ALTER TABLE `graph_insight_summary` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `graph_outbox_event`
--

DROP TABLE IF EXISTS `graph_outbox_event`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `graph_outbox_event` (
  `sequence` bigint NOT NULL AUTO_INCREMENT,
  `event_id` char(36) NOT NULL,
  `tenant_id` varchar(64) NOT NULL,
  `kb_uid` char(36) NOT NULL,
  `graph_generation` char(36) NOT NULL,
  `aggregate_type` varchar(32) NOT NULL,
  `aggregate_id` char(36) NOT NULL,
  `event_type` varchar(64) NOT NULL,
  `payload` json NOT NULL,
  `created_at` datetime NOT NULL,
  PRIMARY KEY (`sequence`),
  UNIQUE KEY `event_id` (`event_id`),
  KEY `ix_graph_outbox_event_tenant_id` (`tenant_id`),
  KEY `ix_graph_outbox_event_kb_uid` (`kb_uid`),
  KEY `ix_graph_outbox_event_graph_generation` (`graph_generation`),
  KEY `ix_graph_outbox_scope_sequence` (`tenant_id`,`kb_uid`,`graph_generation`,`sequence`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `graph_outbox_event`
--

LOCK TABLES `graph_outbox_event` WRITE;
/*!40000 ALTER TABLE `graph_outbox_event` DISABLE KEYS */;
/*!40000 ALTER TABLE `graph_outbox_event` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `graph_projection_cursor`
--

DROP TABLE IF EXISTS `graph_projection_cursor`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `graph_projection_cursor` (
  `id` char(36) NOT NULL,
  `tenant_id` varchar(64) NOT NULL,
  `kb_uid` char(36) NOT NULL,
  `graph_generation` char(36) NOT NULL,
  `projector` varchar(32) NOT NULL,
  `applied_through_sequence` bigint NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_graph_projection_cursor_scope` (`tenant_id`,`kb_uid`,`graph_generation`,`projector`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `graph_projection_cursor`
--

LOCK TABLES `graph_projection_cursor` WRITE;
/*!40000 ALTER TABLE `graph_projection_cursor` DISABLE KEYS */;
/*!40000 ALTER TABLE `graph_projection_cursor` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `graph_projection_receipt`
--

DROP TABLE IF EXISTS `graph_projection_receipt`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `graph_projection_receipt` (
  `id` char(36) NOT NULL,
  `event_id` char(36) NOT NULL,
  `projector` varchar(32) NOT NULL,
  `status` varchar(24) NOT NULL,
  `attempt` int NOT NULL,
  `max_attempts` int NOT NULL,
  `next_attempt_at` datetime NOT NULL,
  `lease_owner` varchar(128) NOT NULL,
  `lease_expires_at` datetime DEFAULT NULL,
  `last_error_code` varchar(64) NOT NULL,
  `last_error_message` text,
  `applied_at` datetime DEFAULT NULL,
  `applied_sequence` bigint DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_graph_projection_event_target` (`event_id`,`projector`),
  KEY `ix_graph_projection_due` (`projector`,`status`,`next_attempt_at`),
  CONSTRAINT `graph_projection_receipt_ibfk_1` FOREIGN KEY (`event_id`) REFERENCES `graph_outbox_event` (`event_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `graph_projection_receipt`
--

LOCK TABLES `graph_projection_receipt` WRITE;
/*!40000 ALTER TABLE `graph_projection_receipt` DISABLE KEYS */;
/*!40000 ALTER TABLE `graph_projection_receipt` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `knowledge_chunk`
--

DROP TABLE IF EXISTS `knowledge_chunk`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `knowledge_chunk` (
  `id` char(36) NOT NULL,
  `chunk_uid` char(36) NOT NULL,
  `tenant_id` char(36) NOT NULL,
  `kb_uid` char(36) NOT NULL,
  `file_uid` char(36) NOT NULL,
  `item_id` char(36) DEFAULT NULL,
  `generation` char(36) NOT NULL DEFAULT '0',
  `chunk_text` text NOT NULL COMMENT 'Chunk text',
  `chunk_index` int DEFAULT NULL COMMENT 'Chunk index',
  `chunk_type` varchar(16) DEFAULT NULL COMMENT 'child / parent',
  `parent_id` char(36) DEFAULT NULL COMMENT 'Child chunk''s parent row ID',
  `parent_chunk_uid` char(36) DEFAULT NULL,
  `page_number` int DEFAULT NULL,
  `char_start` int DEFAULT NULL,
  `char_end` int DEFAULT NULL,
  `token_start` int DEFAULT NULL,
  `token_end` int DEFAULT NULL,
  `title_path` json DEFAULT NULL,
  `embedding_id` varchar(100) DEFAULT NULL COMMENT 'Milvus vector ID',
  `extra_meta` json DEFAULT NULL COMMENT 'Page, position, and other metadata',
  `created_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_knowledge_chunk_uid_generation` (`chunk_uid`,`generation`),
  KEY `item_id` (`item_id`),
  KEY `parent_id` (`parent_id`),
  CONSTRAINT `knowledge_chunk_ibfk_1` FOREIGN KEY (`item_id`) REFERENCES `knowledge_item` (`id`) ON DELETE CASCADE,
  CONSTRAINT `knowledge_chunk_ibfk_2` FOREIGN KEY (`parent_id`) REFERENCES `knowledge_chunk` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `knowledge_chunk`
--

LOCK TABLES `knowledge_chunk` WRITE;
/*!40000 ALTER TABLE `knowledge_chunk` DISABLE KEYS */;
/*!40000 ALTER TABLE `knowledge_chunk` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `knowledge_citation`
--

DROP TABLE IF EXISTS `knowledge_citation`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `knowledge_citation` (
  `id` char(36) NOT NULL,
  `tenant_id` char(36) NOT NULL,
  `kb_uid` char(36) NOT NULL,
  `file_uid` char(36) DEFAULT NULL,
  `chunk_uid` char(36) DEFAULT NULL,
  `citation_text` text,
  `created_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `knowledge_citation`
--

LOCK TABLES `knowledge_citation` WRITE;
/*!40000 ALTER TABLE `knowledge_citation` DISABLE KEYS */;
/*!40000 ALTER TABLE `knowledge_citation` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `knowledge_entity`
--

DROP TABLE IF EXISTS `knowledge_entity`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `knowledge_entity` (
  `id` char(36) NOT NULL,
  `user_id` char(36) NOT NULL,
  `tenant_id` varchar(64) NOT NULL,
  `kb_uid` char(36) NOT NULL,
  `graph_generation` char(36) NOT NULL,
  `entity_type` varchar(64) NOT NULL,
  `canonical_name` varchar(512) NOT NULL,
  `normalized_key` varchar(512) NOT NULL,
  `aliases` json DEFAULT NULL,
  `description` text,
  `confidence` float DEFAULT NULL,
  `status` varchar(32) DEFAULT NULL,
  `metadata` json DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_entity_scope_type_key` (`tenant_id`,`kb_uid`,`graph_generation`,`entity_type`,`normalized_key`),
  KEY `ix_knowledge_entity_tenant_id` (`tenant_id`),
  KEY `ix_knowledge_entity_status` (`status`),
  KEY `ix_entity_lookup` (`user_id`,`normalized_key`),
  KEY `ix_knowledge_entity_normalized_key` (`normalized_key`),
  KEY `ix_knowledge_entity_user_id` (`user_id`),
  KEY `ix_knowledge_entity_kb_uid` (`kb_uid`),
  KEY `ix_entity_scope` (`tenant_id`,`kb_uid`,`graph_generation`,`normalized_key`),
  KEY `ix_knowledge_entity_entity_type` (`entity_type`),
  KEY `ix_knowledge_entity_graph_generation` (`graph_generation`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `knowledge_entity`
--

LOCK TABLES `knowledge_entity` WRITE;
/*!40000 ALTER TABLE `knowledge_entity` DISABLE KEYS */;
/*!40000 ALTER TABLE `knowledge_entity` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `knowledge_file`
--

DROP TABLE IF EXISTS `knowledge_file`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `knowledge_file` (
  `id` char(36) NOT NULL,
  `file_uid` char(36) NOT NULL,
  `kb_uid` char(36) NOT NULL,
  `tenant_id` char(36) NOT NULL,
  `user_id` char(36) DEFAULT NULL COMMENT 'Legacy user id',
  `topic_id` char(36) DEFAULT NULL,
  `item_id` char(36) DEFAULT NULL,
  `title` varchar(255) DEFAULT NULL COMMENT 'Resource title',
  `storage_uri` varchar(1024) DEFAULT NULL,
  `relative_path` varchar(1024) DEFAULT NULL,
  `original_name` varchar(255) DEFAULT NULL COMMENT 'Original filename',
  `source_kind` varchar(64) DEFAULT NULL,
  `source_id` varchar(128) DEFAULT NULL,
  `system_type` varchar(64) DEFAULT NULL,
  `media_type` varchar(64) DEFAULT NULL COMMENT 'document/image/audio/video',
  `mime_type` varchar(100) DEFAULT NULL COMMENT 'MIME type',
  `file_type` varchar(20) DEFAULT NULL COMMENT 'Legacy file extension',
  `content_sha256` char(64) DEFAULT NULL,
  `size_bytes` bigint DEFAULT NULL,
  `file_size` bigint DEFAULT NULL COMMENT 'Legacy file size in bytes',
  `md5` varchar(32) DEFAULT NULL COMMENT 'File MD5',
  `file_path` varchar(500) DEFAULT NULL COMMENT 'Legacy stored file path',
  `parser_config_snapshot` json DEFAULT NULL,
  `chunk_config_snapshot` json DEFAULT NULL,
  `parse_status` varchar(24) NOT NULL DEFAULT 'pending',
  `index_status` varchar(24) NOT NULL DEFAULT 'pending',
  `graph_status` varchar(24) NOT NULL DEFAULT 'pending',
  `parsed_content_version` int NOT NULL DEFAULT '0',
  `active_index_generation` char(36) DEFAULT NULL,
  `parse_error` json DEFAULT NULL,
  `index_error` json DEFAULT NULL,
  `graph_error` json DEFAULT NULL,
  `parse_started_at` datetime DEFAULT NULL,
  `parse_finished_at` datetime DEFAULT NULL,
  `index_started_at` datetime DEFAULT NULL,
  `index_finished_at` datetime DEFAULT NULL,
  `graph_started_at` datetime DEFAULT NULL,
  `graph_finished_at` datetime DEFAULT NULL,
  `last_job_id` char(36) DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `description` text COMMENT 'Resource description',
  `tags` json DEFAULT NULL COMMENT 'Tags',
  `source_type` varchar(32) DEFAULT NULL COMMENT 'upload',
  `page_count` int DEFAULT NULL COMMENT 'Document page count',
  `content_text` mediumtext COMMENT 'Parsed text',
  `uploaded_at` datetime DEFAULT NULL,
  `last_modified_at` datetime DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `error_message` text COMMENT 'Processing error',
  `governance_status` varchar(24) DEFAULT NULL,
  `governance_progress_current` int DEFAULT NULL,
  `governance_progress_total` int DEFAULT NULL,
  `governance_error_message` text COMMENT 'Governance error',
  `governance_started_at` datetime DEFAULT NULL,
  `governance_finished_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_knowledge_file_file_uid` (`file_uid`),
  KEY `topic_id` (`topic_id`),
  KEY `item_id` (`item_id`),
  KEY `ix_knowledge_file_system_type` (`system_type`),
  KEY `ix_knowledge_file_source_kind` (`source_kind`),
  KEY `ix_knowledge_file_source_id` (`source_id`),
  CONSTRAINT `knowledge_file_ibfk_1` FOREIGN KEY (`topic_id`) REFERENCES `knowledge_topic` (`id`) ON DELETE CASCADE,
  CONSTRAINT `knowledge_file_ibfk_2` FOREIGN KEY (`item_id`) REFERENCES `knowledge_item` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `knowledge_file`
--

LOCK TABLES `knowledge_file` WRITE;
/*!40000 ALTER TABLE `knowledge_file` DISABLE KEYS */;
INSERT INTO `knowledge_file` VALUES ('01a88b31-95f8-4e67-997a-b9ced3072d22','55953165-7750-4d24-a0a2-42e7547bcec5','3d2c5370-4453-4fd0-b9a2-95fb3014912e','default-user',NULL,NULL,NULL,NULL,'local://default-user/3d2c5370-4453-4fd0-b9a2-95fb3014912e/55953165-7750-4d24-a0a2-42e7547bcec5/s10044-025-01455-4.pdf','','s10044-025-01455-4.pdf',NULL,NULL,NULL,'document','application/pdf',NULL,'d692dc960b4b6d4753e074ffb74a33aa64a7abf455c3bdbfc16481d9d8453862',2643832,NULL,NULL,NULL,'null','null','failed','pending','pending',0,NULL,'{\"code\": \"PARSE_ERROR\", \"message\": \"[Errno 2] No such file or directory: \'/app/uploads_data/default-user/3d2c5370-4453-4fd0-b9a2-95fb3014912e/55953165-7750-4d24-a0a2-42e7547bcec5/s10044-025-01455-4.pdf\'\"}',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'77ad1926-7519-434d-b9a3-3bce0b16e74e',NULL,NULL,NULL,'upload',NULL,NULL,'2026-08-01 00:49:18','2026-08-01 01:00:25','2026-08-01 00:49:18','2026-08-01 01:00:25',NULL,'not_started',0,0,NULL,NULL,NULL),('0317edb9-426d-409c-9e88-7ee2a1c6f64f','ffc3c98a-017d-4f42-9b9f-9311bdad0687','3d2c5370-4453-4fd0-b9a2-95fb3014912e','default-user',NULL,NULL,NULL,NULL,'local://default-user/3d2c5370-4453-4fd0-b9a2-95fb3014912e/ffc3c98a-017d-4f42-9b9f-9311bdad0687/11521_AF_UMC_An_Alignment_Free.pdf','','11521_AF_UMC_An_Alignment_Free.pdf',NULL,NULL,NULL,'document','application/pdf',NULL,'cad307cef385793be617e0deb7a1a827f5a67cfb11f098ea5f53286aad23e010',7840150,NULL,NULL,NULL,'null','null','failed','pending','pending',0,NULL,'{\"code\": \"PARSE_ERROR\", \"message\": \"[Errno 2] No such file or directory: \'/app/uploads_data/default-user/3d2c5370-4453-4fd0-b9a2-95fb3014912e/ffc3c98a-017d-4f42-9b9f-9311bdad0687/11521_AF_UMC_An_Alignment_Free.pdf\'\"}',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'8337aec6-e3d1-4411-a55f-919a4d3812ff',NULL,NULL,NULL,'upload',NULL,NULL,'2026-08-01 00:49:22','2026-08-01 01:00:26','2026-08-01 00:49:22','2026-08-01 01:00:26',NULL,'not_started',0,0,NULL,NULL,NULL),('2bbd760b-f320-4c56-9ae7-e9f78f241ea4','c1582498-8d4e-4dbb-ac42-3c451a3dd346','3d2c5370-4453-4fd0-b9a2-95fb3014912e','default-user',NULL,NULL,NULL,NULL,'local://default-user/3d2c5370-4453-4fd0-b9a2-95fb3014912e/c1582498-8d4e-4dbb-ac42-3c451a3dd346/33725-Article Text-37793-1-2-20250410.pdf','','33725-Article Text-37793-1-2-20250410.pdf',NULL,NULL,NULL,'document','application/pdf',NULL,'2d63ca265732c4770e6f85038f6f5b98da87491572e69586be3e54449597d360',1270539,NULL,NULL,NULL,'null','null','failed','pending','pending',0,NULL,'{\"code\": \"PARSE_ERROR\", \"message\": \"[Errno 2] No such file or directory: \'/app/uploads_data/default-user/3d2c5370-4453-4fd0-b9a2-95fb3014912e/c1582498-8d4e-4dbb-ac42-3c451a3dd346/33725-Article Text-37793-1-2-20250410.pdf\'\"}',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'94143d8f-b8d0-4ba3-8143-d2aed7a186c1',NULL,NULL,NULL,'upload',NULL,NULL,'2026-08-01 00:49:18','2026-08-01 01:00:26','2026-08-01 00:49:18','2026-08-01 01:00:26',NULL,'not_started',0,0,NULL,NULL,NULL),('60e6d7ff-b418-4080-8d3e-0a0a9c82606c','4165a080-19a5-4faa-bf8a-9a9041ac5e0c','3d2c5370-4453-4fd0-b9a2-95fb3014912e','default-user',NULL,NULL,NULL,NULL,'local://default-user/3d2c5370-4453-4fd0-b9a2-95fb3014912e/4165a080-19a5-4faa-bf8a-9a9041ac5e0c/34277-Article Text-38345-1-2-20250410.pdf','','34277-Article Text-38345-1-2-20250410.pdf',NULL,NULL,NULL,'document','application/pdf',NULL,'94bbe7249c01b8271ca347d84374671855fb10370bf4af8e19e20d8247b2690c',1940608,NULL,NULL,NULL,'null','null','failed','pending','pending',0,NULL,'{\"code\": \"PARSE_ERROR\", \"message\": \"[Errno 2] No such file or directory: \'/app/uploads_data/default-user/3d2c5370-4453-4fd0-b9a2-95fb3014912e/4165a080-19a5-4faa-bf8a-9a9041ac5e0c/34277-Article Text-38345-1-2-20250410.pdf\'\"}',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'fb2aa3b3-9cb5-4c82-9de6-4150c74ebf7a',NULL,NULL,NULL,'upload',NULL,NULL,'2026-08-01 00:49:20','2026-08-01 01:00:22','2026-08-01 00:49:20','2026-08-01 01:00:22',NULL,'not_started',0,0,NULL,NULL,NULL),('838f4c9a-41bb-4953-b0a2-3ba5f06a145f','43382813-4909-4718-a736-793bb97c9af3','3d2c5370-4453-4fd0-b9a2-95fb3014912e','default-user',NULL,NULL,NULL,NULL,'local://default-user/3d2c5370-4453-4fd0-b9a2-95fb3014912e/43382813-4909-4718-a736-793bb97c9af3/The_Name_of_the_Title_Is_Hope.pdf','','The_Name_of_the_Title_Is_Hope.pdf',NULL,NULL,NULL,'document','application/pdf',NULL,'7955f18ee2aecdfd916f99f004a0c92fd41d8a2c840138d0a2a47af1932d29d0',14476255,NULL,NULL,NULL,'null','null','failed','pending','pending',0,NULL,'{\"code\": \"PARSE_ERROR\", \"message\": \"[Errno 2] No such file or directory: \'/app/uploads_data/default-user/3d2c5370-4453-4fd0-b9a2-95fb3014912e/43382813-4909-4718-a736-793bb97c9af3/The_Name_of_the_Title_Is_Hope.pdf\'\"}',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'07403566-da36-4930-83cf-14cc2182eb67',NULL,NULL,NULL,'upload',NULL,NULL,'2026-08-01 00:49:21','2026-08-01 01:00:24','2026-08-01 00:49:21','2026-08-01 01:00:24',NULL,'not_started',0,0,NULL,NULL,NULL),('cbbfc0ca-0670-46fc-ac82-41c1abf8ab59','18df7506-df9a-44b1-939e-7d5f9cff6348','3d2c5370-4453-4fd0-b9a2-95fb3014912e','default-user',NULL,NULL,NULL,NULL,'local://default-user/3d2c5370-4453-4fd0-b9a2-95fb3014912e/18df7506-df9a-44b1-939e-7d5f9cff6348/1-s2.0-S0950705125009876-main.pdf','','1-s2.0-S0950705125009876-main.pdf',NULL,NULL,NULL,'document','application/pdf',NULL,'64373bc214a0214f9ba7956dd8f0c430afe7c7d1f77d05604e36b82ed2b3ed5b',3534956,NULL,NULL,NULL,'null','null','failed','pending','pending',0,NULL,'{\"code\": \"PARSE_ERROR\", \"message\": \"[Errno 2] No such file or directory: \'/app/uploads_data/default-user/3d2c5370-4453-4fd0-b9a2-95fb3014912e/18df7506-df9a-44b1-939e-7d5f9cff6348/1-s2.0-S0950705125009876-main.pdf\'\"}',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'2b908b3b-211d-462d-b3ce-804bf99658a5',NULL,NULL,NULL,'upload',NULL,NULL,'2026-08-01 00:49:20','2026-08-01 01:00:21','2026-08-01 00:49:20','2026-08-01 01:00:21',NULL,'not_started',0,0,NULL,NULL,NULL);
/*!40000 ALTER TABLE `knowledge_file` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `knowledge_graph_generation`
--

DROP TABLE IF EXISTS `knowledge_graph_generation`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `knowledge_graph_generation` (
  `id` char(36) NOT NULL,
  `tenant_id` varchar(64) NOT NULL,
  `kb_uid` char(36) NOT NULL,
  `generation` char(36) NOT NULL,
  `extractor_config_hash` varchar(64) NOT NULL,
  `status` varchar(24) NOT NULL,
  `barrier_sequence` bigint DEFAULT NULL,
  `failure_code` varchar(64) NOT NULL,
  `failure_message` text,
  `created_at` datetime NOT NULL,
  `activated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_graph_generation_scope` (`tenant_id`,`kb_uid`,`generation`),
  KEY `ix_knowledge_graph_generation_kb_uid` (`kb_uid`),
  KEY `ix_knowledge_graph_generation_tenant_id` (`tenant_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `knowledge_graph_generation`
--

LOCK TABLES `knowledge_graph_generation` WRITE;
/*!40000 ALTER TABLE `knowledge_graph_generation` DISABLE KEYS */;
/*!40000 ALTER TABLE `knowledge_graph_generation` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `knowledge_item`
--

DROP TABLE IF EXISTS `knowledge_item`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `knowledge_item` (
  `id` char(36) NOT NULL,
  `tenant_id` char(36) NOT NULL,
  `kb_uid` char(36) NOT NULL,
  `title` varchar(255) NOT NULL COMMENT 'Title',
  `content` mediumtext COMMENT 'Markdown content',
  `normalized_markdown` mediumtext,
  `summary` text COMMENT 'AI generated summary',
  `source_type` varchar(32) DEFAULT NULL COMMENT 'file/url/chat/manual',
  `source_ref` varchar(500) DEFAULT NULL COMMENT 'Original file path, URL, or chat ID',
  `content_version` int NOT NULL DEFAULT '1',
  `tags` json DEFAULT NULL COMMENT 'Tag list',
  `category` varchar(255) DEFAULT NULL COMMENT 'Category path',
  `status` varchar(24) DEFAULT NULL COMMENT 'draft/published/archived',
  `user_id` char(36) DEFAULT NULL COMMENT 'Legacy user id',
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `knowledge_item`
--

LOCK TABLES `knowledge_item` WRITE;
/*!40000 ALTER TABLE `knowledge_item` DISABLE KEYS */;
/*!40000 ALTER TABLE `knowledge_item` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `knowledge_job`
--

DROP TABLE IF EXISTS `knowledge_job`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `knowledge_job` (
  `id` char(36) NOT NULL,
  `tenant_id` char(36) NOT NULL,
  `kb_uid` char(36) NOT NULL,
  `file_uid` char(36) DEFAULT NULL,
  `idempotency_key` varchar(255) NOT NULL,
  `payload` json DEFAULT NULL,
  `result` json DEFAULT NULL,
  `job_type` varchar(32) DEFAULT NULL COMMENT 'ingest / governance',
  `resource_id` char(36) DEFAULT NULL,
  `item_id` char(36) DEFAULT NULL,
  `topic_id` char(36) DEFAULT NULL,
  `status` varchar(24) NOT NULL DEFAULT 'queued',
  `priority` int NOT NULL DEFAULT '100',
  `attempt` int NOT NULL DEFAULT '0',
  `attempts` int NOT NULL DEFAULT '0',
  `max_attempts` int NOT NULL DEFAULT '3',
  `next_run_at` datetime DEFAULT NULL,
  `progress_current` int NOT NULL DEFAULT '0',
  `progress_total` int NOT NULL DEFAULT '0',
  `stage` varchar(64) NOT NULL DEFAULT '',
  `error_code` varchar(64) DEFAULT NULL,
  `error_message` text,
  `retryable` tinyint(1) NOT NULL DEFAULT '0',
  `lease_owner` varchar(128) DEFAULT NULL,
  `lease_expires_at` datetime DEFAULT NULL,
  `heartbeat_at` datetime DEFAULT NULL,
  `cancel_requested_at` datetime DEFAULT NULL,
  `canceled_by` char(36) DEFAULT NULL,
  `locked_by` varchar(128) DEFAULT NULL,
  `locked_at` datetime DEFAULT NULL,
  `available_at` datetime DEFAULT NULL,
  `started_at` datetime DEFAULT NULL,
  `finished_at` datetime DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_knowledge_job_idempotency_key` (`idempotency_key`),
  KEY `ix_knowledge_job_status_available_priority_created` (`status`,`available_at`,`priority`,`created_at`),
  KEY `ix_knowledge_job_item_id` (`item_id`),
  KEY `ix_knowledge_job_topic_id` (`topic_id`),
  KEY `ix_knowledge_job_resource_type_status` (`resource_id`,`job_type`,`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `knowledge_job`
--

LOCK TABLES `knowledge_job` WRITE;
/*!40000 ALTER TABLE `knowledge_job` DISABLE KEYS */;
INSERT INTO `knowledge_job` VALUES ('07403566-da36-4930-83cf-14cc2182eb67','default-user','3d2c5370-4453-4fd0-b9a2-95fb3014912e','43382813-4909-4718-a736-793bb97c9af3','3d2c5370-4453-4fd0-b9a2-95fb3014912e:43382813-4909-4718-a736-793bb97c9af3:parse:v0:retry:2:2dc1e722-12f4-431b-9abc-ac383a479bec:7efd3306-43bd-421e-9610-27ddd07737a6','{}',NULL,'parse',NULL,NULL,NULL,'queued',100,1,1,3,NULL,0,0,'enqueued','PARSE_ERROR','[Errno 2] No such file or directory: \'/app/uploads_data/default-user/3d2c5370-4453-4fd0-b9a2-95fb3014912e/43382813-4909-4718-a736-793bb97c9af3/The_Name_of_the_Title_Is_Hope.pdf\'',1,NULL,NULL,'2026-08-01 01:00:24',NULL,NULL,NULL,NULL,'2026-08-01 01:00:24','2026-08-01 01:00:24',NULL,'2026-08-01 01:00:24','2026-08-01 01:00:24'),('2b908b3b-211d-462d-b3ce-804bf99658a5','default-user','3d2c5370-4453-4fd0-b9a2-95fb3014912e','18df7506-df9a-44b1-939e-7d5f9cff6348','3d2c5370-4453-4fd0-b9a2-95fb3014912e:18df7506-df9a-44b1-939e-7d5f9cff6348:parse:v0:retry:2:36308e46-8db4-48df-a214-1a71a9d3b945:614b043e-08d5-4596-9c5d-43a09d5ab6b3','{}',NULL,'parse',NULL,NULL,NULL,'queued',100,1,1,3,NULL,0,0,'enqueued','PARSE_ERROR','[Errno 2] No such file or directory: \'/app/uploads_data/default-user/3d2c5370-4453-4fd0-b9a2-95fb3014912e/18df7506-df9a-44b1-939e-7d5f9cff6348/1-s2.0-S0950705125009876-main.pdf\'',1,NULL,NULL,'2026-08-01 01:00:21',NULL,NULL,NULL,NULL,'2026-08-01 01:00:21','2026-08-01 01:00:21',NULL,'2026-08-01 01:00:21','2026-08-01 01:00:21'),('2dc1e722-12f4-431b-9abc-ac383a479bec','default-user','3d2c5370-4453-4fd0-b9a2-95fb3014912e','43382813-4909-4718-a736-793bb97c9af3','3d2c5370-4453-4fd0-b9a2-95fb3014912e:43382813-4909-4718-a736-793bb97c9af3:parse:v0','{\"auto_index\": true}',NULL,'parse',NULL,NULL,NULL,'failed',100,3,3,3,NULL,0,0,'enqueued','PARSE_ERROR','[Errno 2] No such file or directory: \'/app/uploads_data/default-user/3d2c5370-4453-4fd0-b9a2-95fb3014912e/43382813-4909-4718-a736-793bb97c9af3/The_Name_of_the_Title_Is_Hope.pdf\'',0,'ingest-0-ed1fa633408c-90eea579','2026-08-01 01:02:15','2026-08-01 01:00:15',NULL,NULL,NULL,NULL,'2026-08-01 00:49:21','2026-08-01 01:00:15','2026-08-01 01:00:15','2026-08-01 00:49:21','2026-08-01 01:00:15'),('36308e46-8db4-48df-a214-1a71a9d3b945','default-user','3d2c5370-4453-4fd0-b9a2-95fb3014912e','18df7506-df9a-44b1-939e-7d5f9cff6348','3d2c5370-4453-4fd0-b9a2-95fb3014912e:18df7506-df9a-44b1-939e-7d5f9cff6348:parse:v0','{\"auto_index\": true}',NULL,'parse',NULL,NULL,NULL,'failed',100,3,3,3,NULL,0,0,'enqueued','PARSE_ERROR','[Errno 2] No such file or directory: \'/app/uploads_data/default-user/3d2c5370-4453-4fd0-b9a2-95fb3014912e/18df7506-df9a-44b1-939e-7d5f9cff6348/1-s2.0-S0950705125009876-main.pdf\'',0,'ingest-0-ed1fa633408c-90eea579','2026-08-01 01:02:14','2026-08-01 01:00:14',NULL,NULL,NULL,NULL,'2026-08-01 00:49:20','2026-08-01 01:00:14','2026-08-01 01:00:14','2026-08-01 00:49:20','2026-08-01 01:00:14'),('74193e19-0816-4892-92b4-3947b94612c1','default-user','3d2c5370-4453-4fd0-b9a2-95fb3014912e','4165a080-19a5-4faa-bf8a-9a9041ac5e0c','3d2c5370-4453-4fd0-b9a2-95fb3014912e:4165a080-19a5-4faa-bf8a-9a9041ac5e0c:parse:v0','{\"auto_index\": true}',NULL,'parse',NULL,NULL,NULL,'failed',100,3,3,3,NULL,0,0,'enqueued','PARSE_ERROR','[Errno 2] No such file or directory: \'/app/uploads_data/default-user/3d2c5370-4453-4fd0-b9a2-95fb3014912e/4165a080-19a5-4faa-bf8a-9a9041ac5e0c/34277-Article Text-38345-1-2-20250410.pdf\'',0,'ingest-0-ed1fa633408c-90eea579','2026-08-01 01:02:15','2026-08-01 01:00:15',NULL,NULL,NULL,NULL,'2026-08-01 00:49:20','2026-08-01 01:00:15','2026-08-01 01:00:15','2026-08-01 00:49:20','2026-08-01 01:00:15'),('77ad1926-7519-434d-b9a3-3bce0b16e74e','default-user','3d2c5370-4453-4fd0-b9a2-95fb3014912e','55953165-7750-4d24-a0a2-42e7547bcec5','3d2c5370-4453-4fd0-b9a2-95fb3014912e:55953165-7750-4d24-a0a2-42e7547bcec5:parse:v0:retry:2:b2e7e90b-c528-408b-803f-fbba4c18e1d8:fc38087f-af09-4933-bdb9-0e1e3654337b','{}',NULL,'parse',NULL,NULL,NULL,'queued',100,1,1,3,NULL,0,0,'enqueued','PARSE_ERROR','[Errno 2] No such file or directory: \'/app/uploads_data/default-user/3d2c5370-4453-4fd0-b9a2-95fb3014912e/55953165-7750-4d24-a0a2-42e7547bcec5/s10044-025-01455-4.pdf\'',1,NULL,NULL,'2026-08-01 01:00:25',NULL,NULL,NULL,NULL,'2026-08-01 01:00:25','2026-08-01 01:00:25',NULL,'2026-08-01 01:00:25','2026-08-01 01:00:25'),('8337aec6-e3d1-4411-a55f-919a4d3812ff','default-user','3d2c5370-4453-4fd0-b9a2-95fb3014912e','ffc3c98a-017d-4f42-9b9f-9311bdad0687','3d2c5370-4453-4fd0-b9a2-95fb3014912e:ffc3c98a-017d-4f42-9b9f-9311bdad0687:parse:v0','{\"auto_index\": true}',NULL,'parse',NULL,NULL,NULL,'failed',100,3,3,3,NULL,0,0,'enqueued','PARSE_ERROR','[Errno 2] No such file or directory: \'/app/uploads_data/default-user/3d2c5370-4453-4fd0-b9a2-95fb3014912e/ffc3c98a-017d-4f42-9b9f-9311bdad0687/11521_AF_UMC_An_Alignment_Free.pdf\'',0,'ingest-0-ed1fa633408c-90eea579','2026-08-01 01:02:26','2026-08-01 01:00:26',NULL,NULL,NULL,NULL,'2026-08-01 00:49:22','2026-08-01 01:00:26','2026-08-01 01:00:26','2026-08-01 00:49:22','2026-08-01 01:00:26'),('94143d8f-b8d0-4ba3-8143-d2aed7a186c1','default-user','3d2c5370-4453-4fd0-b9a2-95fb3014912e','c1582498-8d4e-4dbb-ac42-3c451a3dd346','3d2c5370-4453-4fd0-b9a2-95fb3014912e:c1582498-8d4e-4dbb-ac42-3c451a3dd346:parse:v0','{\"auto_index\": true}',NULL,'parse',NULL,NULL,NULL,'failed',100,3,3,3,NULL,0,0,'enqueued','PARSE_ERROR','[Errno 2] No such file or directory: \'/app/uploads_data/default-user/3d2c5370-4453-4fd0-b9a2-95fb3014912e/c1582498-8d4e-4dbb-ac42-3c451a3dd346/33725-Article Text-37793-1-2-20250410.pdf\'',0,'ingest-0-ed1fa633408c-90eea579','2026-08-01 01:02:25','2026-08-01 01:00:26',NULL,NULL,NULL,NULL,'2026-08-01 00:49:18','2026-08-01 01:00:26','2026-08-01 01:00:26','2026-08-01 00:49:18','2026-08-01 01:00:26'),('b2e7e90b-c528-408b-803f-fbba4c18e1d8','default-user','3d2c5370-4453-4fd0-b9a2-95fb3014912e','55953165-7750-4d24-a0a2-42e7547bcec5','3d2c5370-4453-4fd0-b9a2-95fb3014912e:55953165-7750-4d24-a0a2-42e7547bcec5:parse:v0','{\"auto_index\": true}',NULL,'parse',NULL,NULL,NULL,'failed',100,3,3,3,NULL,0,0,'enqueued','PARSE_ERROR','[Errno 2] No such file or directory: \'/app/uploads_data/default-user/3d2c5370-4453-4fd0-b9a2-95fb3014912e/55953165-7750-4d24-a0a2-42e7547bcec5/s10044-025-01455-4.pdf\'',0,'ingest-0-ed1fa633408c-90eea579','2026-08-01 01:02:16','2026-08-01 01:00:16',NULL,NULL,NULL,NULL,'2026-08-01 00:49:18','2026-08-01 01:00:16','2026-08-01 01:00:16','2026-08-01 00:49:18','2026-08-01 01:00:16'),('fb2aa3b3-9cb5-4c82-9de6-4150c74ebf7a','default-user','3d2c5370-4453-4fd0-b9a2-95fb3014912e','4165a080-19a5-4faa-bf8a-9a9041ac5e0c','3d2c5370-4453-4fd0-b9a2-95fb3014912e:4165a080-19a5-4faa-bf8a-9a9041ac5e0c:parse:v0:retry:2:74193e19-0816-4892-92b4-3947b94612c1:bce4d352-758b-4cdf-8a25-d05cc554ee79','{}',NULL,'parse',NULL,NULL,NULL,'queued',100,1,1,3,NULL,0,0,'enqueued','PARSE_ERROR','[Errno 2] No such file or directory: \'/app/uploads_data/default-user/3d2c5370-4453-4fd0-b9a2-95fb3014912e/4165a080-19a5-4faa-bf8a-9a9041ac5e0c/34277-Article Text-38345-1-2-20250410.pdf\'',1,NULL,NULL,'2026-08-01 01:00:22',NULL,NULL,NULL,NULL,'2026-08-01 01:00:22','2026-08-01 01:00:22',NULL,'2026-08-01 01:00:22','2026-08-01 01:00:22');
/*!40000 ALTER TABLE `knowledge_job` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `knowledge_topic`
--

DROP TABLE IF EXISTS `knowledge_topic`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `knowledge_topic` (
  `id` char(36) NOT NULL,
  `user_id` char(36) DEFAULT NULL COMMENT 'Legacy user id',
  `kb_uid` char(36) NOT NULL,
  `tenant_id` char(36) NOT NULL,
  `owner_user_id` char(36) NOT NULL,
  `name` varchar(255) NOT NULL COMMENT 'Topic name',
  `description` text COMMENT 'Topic description',
  `status` varchar(24) NOT NULL DEFAULT 'active',
  `deleted_at` datetime DEFAULT NULL,
  `version` int NOT NULL DEFAULT '1',
  `embedding_profile` json DEFAULT NULL,
  `parser_config` json DEFAULT NULL,
  `chunk_config` json DEFAULT NULL,
  `retrieval_config` json DEFAULT NULL,
  `graph_config` json DEFAULT NULL,
  `active_index_generation` char(36) DEFAULT NULL,
  `active_graph_generation` char(36) DEFAULT NULL,
  `mindmap` json DEFAULT NULL,
  `mindmap_version` int DEFAULT NULL,
  `mindmap_generated_at` datetime DEFAULT NULL,
  `sample_questions` json DEFAULT NULL,
  `sample_questions_version` int DEFAULT NULL,
  `system_type` varchar(64) DEFAULT NULL,
  `is_system` tinyint(1) NOT NULL DEFAULT '0',
  `delete_disabled` tinyint(1) NOT NULL DEFAULT '0',
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_knowledge_topic_kb_uid` (`kb_uid`),
  KEY `ix_knowledge_topic_system_type` (`system_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `knowledge_topic`
--

LOCK TABLES `knowledge_topic` WRITE;
/*!40000 ALTER TABLE `knowledge_topic` DISABLE KEYS */;
INSERT INTO `knowledge_topic` VALUES ('37a7c1e5-74c5-4d23-84a2-4e5c550285e6','default-user','ecd1ea55-f9f5-5326-9187-327b3ec56661','default-user','default-user','个人随手记','系统自动生成的个人资产知识库。','active',NULL,1,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'personal_inbox',1,1,'2026-08-01 00:45:33','2026-08-01 00:45:33'),('5201e344-ef8d-450e-85e7-88ab75176402',NULL,'3d2c5370-4453-4fd0-b9a2-95fb3014912e','default-user','default-user','多视图论文',NULL,'active',NULL,1,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'{\"nodes\": [], \"status\": \"stale\", \"version\": 0, \"stale_reason\": \"file_added\", \"input_revision\": 6}',NULL,NULL,'{\"status\": \"stale\", \"version\": 0, \"questions\": [], \"stale_reason\": \"file_added\", \"input_revision\": 6}',NULL,NULL,0,0,'2026-08-01 00:49:06','2026-08-01 00:49:22');
/*!40000 ALTER TABLE `knowledge_topic` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `memory_draft`
--

DROP TABLE IF EXISTS `memory_draft`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `memory_draft` (
  `id` char(36) NOT NULL,
  `user_id` char(36) NOT NULL,
  `draft_type` varchar(64) NOT NULL,
  `payload` json DEFAULT NULL,
  `decision_hint` varchar(64) DEFAULT NULL,
  `risk_level` varchar(32) DEFAULT NULL,
  `confidence` float DEFAULT NULL,
  `status` varchar(32) DEFAULT NULL,
  `conflict_ids` json DEFAULT NULL,
  `source_id` char(36) DEFAULT NULL,
  `explicitness` float DEFAULT NULL COMMENT 'LLM 判断的显式度 0-1',
  `sensitivity_flag` float DEFAULT NULL COMMENT '是否含敏感个人信息，0/1',
  `auto_confirm_score` float DEFAULT NULL COMMENT '后端规则引擎计算的自动确认综合分',
  `corroboration_count` int DEFAULT NULL COMMENT '跨会话/跨消息印证条数',
  `reviewed_at` datetime DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_memory_draft_risk_level` (`risk_level`),
  KEY `ix_memory_draft_draft_type` (`draft_type`),
  KEY `ix_memory_draft_source_id` (`source_id`),
  KEY `ix_memory_draft_user_id` (`user_id`),
  KEY `ix_memory_draft_status` (`status`),
  CONSTRAINT `memory_draft_ibfk_1` FOREIGN KEY (`source_id`) REFERENCES `memory_source` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `memory_draft`
--

LOCK TABLES `memory_draft` WRITE;
/*!40000 ALTER TABLE `memory_draft` DISABLE KEYS */;
/*!40000 ALTER TABLE `memory_draft` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `memory_entity`
--

DROP TABLE IF EXISTS `memory_entity`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `memory_entity` (
  `id` char(36) NOT NULL,
  `user_id` char(36) NOT NULL,
  `name` varchar(255) NOT NULL,
  `entity_type` varchar(64) DEFAULT NULL,
  `description` text,
  `aliases` json DEFAULT NULL,
  `confidence` float DEFAULT NULL,
  `importance` float DEFAULT NULL,
  `mention_count` int DEFAULT NULL,
  `status` varchar(32) DEFAULT NULL,
  `source_ids` json DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_memory_entity_user_id` (`user_id`),
  KEY `ix_memory_entity_status` (`status`),
  KEY `ix_memory_entity_entity_type` (`entity_type`),
  KEY `ix_memory_entity_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `memory_entity`
--

LOCK TABLES `memory_entity` WRITE;
/*!40000 ALTER TABLE `memory_entity` DISABLE KEYS */;
/*!40000 ALTER TABLE `memory_entity` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `memory_entry`
--

DROP TABLE IF EXISTS `memory_entry`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `memory_entry` (
  `id` char(36) NOT NULL,
  `user_id` char(36) NOT NULL,
  `title` varchar(255) NOT NULL,
  `content` text NOT NULL,
  `memory_type` varchar(32) DEFAULT NULL COMMENT 'preference/fact/goal/context',
  `category` varchar(128) DEFAULT NULL,
  `tags` json DEFAULT NULL,
  `importance` float DEFAULT NULL,
  `source_raw_item_id` char(36) DEFAULT NULL,
  `source_review_id` char(36) DEFAULT NULL,
  `embedding_ref` varchar(255) DEFAULT NULL,
  `embedding_model` varchar(128) DEFAULT NULL,
  `embedding_status` varchar(32) DEFAULT NULL,
  `access_count` int DEFAULT NULL,
  `last_accessed_at` datetime DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_memory_entry_user_id` (`user_id`),
  KEY `ix_memory_entry_memory_type` (`memory_type`),
  KEY `ix_memory_entry_last_accessed_at` (`last_accessed_at`),
  KEY `ix_memory_entry_embedding_status` (`embedding_status`),
  KEY `ix_memory_entry_access_count` (`access_count`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `memory_entry`
--

LOCK TABLES `memory_entry` WRITE;
/*!40000 ALTER TABLE `memory_entry` DISABLE KEYS */;
/*!40000 ALTER TABLE `memory_entry` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `memory_event`
--

DROP TABLE IF EXISTS `memory_event`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `memory_event` (
  `id` char(36) NOT NULL,
  `user_id` char(36) NOT NULL,
  `title` varchar(255) NOT NULL,
  `description` text,
  `event_time` datetime DEFAULT NULL,
  `event_type` varchar(64) DEFAULT NULL,
  `related_entity_ids` json DEFAULT NULL,
  `statement_id` char(36) DEFAULT NULL,
  `confidence` float DEFAULT NULL,
  `status` varchar(32) DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_memory_event_user_id` (`user_id`),
  KEY `ix_memory_event_statement_id` (`statement_id`),
  KEY `ix_memory_event_status` (`status`),
  KEY `ix_memory_event_event_time` (`event_time`),
  KEY `ix_memory_event_event_type` (`event_type`),
  CONSTRAINT `memory_event_ibfk_1` FOREIGN KEY (`statement_id`) REFERENCES `memory_statement` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `memory_event`
--

LOCK TABLES `memory_event` WRITE;
/*!40000 ALTER TABLE `memory_event` DISABLE KEYS */;
/*!40000 ALTER TABLE `memory_event` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `memory_extraction_run`
--

DROP TABLE IF EXISTS `memory_extraction_run`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `memory_extraction_run` (
  `id` char(36) NOT NULL,
  `user_id` char(36) NOT NULL,
  `trigger_type` varchar(32) DEFAULT NULL COMMENT 'scheduled/manual/instant',
  `sessions_scanned` int DEFAULT NULL,
  `sessions_extracted` int DEFAULT NULL,
  `candidates_found` int DEFAULT NULL,
  `auto_confirmed` int DEFAULT NULL,
  `inbox_created` int DEFAULT NULL,
  `skipped` int DEFAULT NULL,
  `errors` int DEFAULT NULL,
  `duration_ms` int DEFAULT NULL,
  `details` json DEFAULT NULL COMMENT 'per-session breakdown',
  `created_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_memory_extraction_run_trigger_type` (`trigger_type`),
  KEY `ix_memory_extraction_run_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `memory_extraction_run`
--

LOCK TABLES `memory_extraction_run` WRITE;
/*!40000 ALTER TABLE `memory_extraction_run` DISABLE KEYS */;
/*!40000 ALTER TABLE `memory_extraction_run` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `memory_insight`
--

DROP TABLE IF EXISTS `memory_insight`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `memory_insight` (
  `id` char(36) NOT NULL,
  `user_id` char(36) NOT NULL,
  `theme` varchar(128) NOT NULL,
  `content` text NOT NULL,
  `insight_type` varchar(64) DEFAULT NULL,
  `source_statement_ids` json DEFAULT NULL,
  `confidence` float DEFAULT NULL,
  `importance` float DEFAULT NULL,
  `status` varchar(32) DEFAULT NULL,
  `valid_from` datetime DEFAULT NULL,
  `embedding_ref` varchar(255) DEFAULT NULL,
  `embedding_model` varchar(128) DEFAULT NULL,
  `embedding_status` varchar(32) DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_memory_insight_theme` (`theme`),
  KEY `ix_memory_insight_user_id` (`user_id`),
  KEY `ix_memory_insight_insight_type` (`insight_type`),
  KEY `ix_memory_insight_embedding_status` (`embedding_status`),
  KEY `ix_memory_insight_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `memory_insight`
--

LOCK TABLES `memory_insight` WRITE;
/*!40000 ALTER TABLE `memory_insight` DISABLE KEYS */;
/*!40000 ALTER TABLE `memory_insight` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `memory_relation`
--

DROP TABLE IF EXISTS `memory_relation`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `memory_relation` (
  `id` char(36) NOT NULL,
  `user_id` char(36) NOT NULL,
  `subject_entity_id` char(36) NOT NULL,
  `predicate` varchar(64) NOT NULL,
  `object_entity_id` char(36) NOT NULL,
  `statement_id` char(36) DEFAULT NULL,
  `confidence` float DEFAULT NULL,
  `status` varchar(32) DEFAULT NULL,
  `valid_from` datetime DEFAULT NULL,
  `valid_until` datetime DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_memory_relation_predicate` (`predicate`),
  KEY `ix_memory_relation_statement_id` (`statement_id`),
  KEY `ix_memory_relation_subject_entity_id` (`subject_entity_id`),
  KEY `ix_memory_relation_object_entity_id` (`object_entity_id`),
  KEY `ix_memory_relation_status` (`status`),
  KEY `ix_memory_relation_user_id` (`user_id`),
  CONSTRAINT `memory_relation_ibfk_1` FOREIGN KEY (`subject_entity_id`) REFERENCES `memory_entity` (`id`),
  CONSTRAINT `memory_relation_ibfk_2` FOREIGN KEY (`object_entity_id`) REFERENCES `memory_entity` (`id`),
  CONSTRAINT `memory_relation_ibfk_3` FOREIGN KEY (`statement_id`) REFERENCES `memory_statement` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `memory_relation`
--

LOCK TABLES `memory_relation` WRITE;
/*!40000 ALTER TABLE `memory_relation` DISABLE KEYS */;
/*!40000 ALTER TABLE `memory_relation` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `memory_source`
--

DROP TABLE IF EXISTS `memory_source`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `memory_source` (
  `id` char(36) NOT NULL,
  `user_id` char(36) NOT NULL,
  `source_type` varchar(64) NOT NULL,
  `source_id` varchar(128) DEFAULT NULL,
  `session_id` char(36) DEFAULT NULL,
  `message_id` char(36) DEFAULT NULL,
  `span_text` text,
  `occurred_at` datetime DEFAULT NULL,
  `metadata` json DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_memory_source_source_type` (`source_type`),
  KEY `ix_memory_source_user_id` (`user_id`),
  KEY `ix_memory_source_session_id` (`session_id`),
  KEY `ix_memory_source_message_id` (`message_id`),
  KEY `ix_memory_source_occurred_at` (`occurred_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `memory_source`
--

LOCK TABLES `memory_source` WRITE;
/*!40000 ALTER TABLE `memory_source` DISABLE KEYS */;
/*!40000 ALTER TABLE `memory_source` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `memory_statement`
--

DROP TABLE IF EXISTS `memory_statement`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `memory_statement` (
  `id` char(36) NOT NULL,
  `user_id` char(36) NOT NULL,
  `content` text NOT NULL,
  `statement_type` varchar(64) DEFAULT NULL,
  `temporal_type` varchar(64) DEFAULT NULL,
  `confidence` float DEFAULT NULL,
  `importance` float DEFAULT NULL,
  `status` varchar(32) DEFAULT NULL,
  `valid_from` datetime DEFAULT NULL,
  `valid_until` datetime DEFAULT NULL,
  `superseded_by_id` char(36) DEFAULT NULL,
  `embedding_ref` varchar(255) DEFAULT NULL,
  `embedding_model` varchar(128) DEFAULT NULL,
  `embedding_status` varchar(32) DEFAULT NULL,
  `access_count` int DEFAULT NULL,
  `last_accessed_at` datetime DEFAULT NULL,
  `source_id` char(36) DEFAULT NULL,
  `explicitness` float DEFAULT NULL COMMENT 'LLM 判断的显式度 0-1',
  `sensitivity_flag` float DEFAULT NULL COMMENT '是否含敏感个人信息，0/1',
  `auto_confirm_score` float DEFAULT NULL COMMENT '后端规则引擎计算的自动确认综合分',
  `corroboration_count` int DEFAULT NULL COMMENT '跨会话/跨消息印证条数',
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_memory_statement_source_id` (`source_id`),
  KEY `ix_memory_statement_statement_type` (`statement_type`),
  KEY `ix_memory_statement_temporal_type` (`temporal_type`),
  KEY `ix_memory_statement_status` (`status`),
  KEY `ix_memory_statement_access_count` (`access_count`),
  KEY `ix_memory_statement_superseded_by_id` (`superseded_by_id`),
  KEY `ix_memory_statement_last_accessed_at` (`last_accessed_at`),
  KEY `ix_memory_statement_embedding_status` (`embedding_status`),
  KEY `ix_memory_statement_user_id` (`user_id`),
  CONSTRAINT `memory_statement_ibfk_1` FOREIGN KEY (`source_id`) REFERENCES `memory_source` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `memory_statement`
--

LOCK TABLES `memory_statement` WRITE;
/*!40000 ALTER TABLE `memory_statement` DISABLE KEYS */;
/*!40000 ALTER TABLE `memory_statement` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `personal_asset`
--

DROP TABLE IF EXISTS `personal_asset`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `personal_asset` (
  `id` char(36) NOT NULL,
  `user_id` char(36) NOT NULL,
  `asset_kind` varchar(64) DEFAULT NULL,
  `title` varchar(255) NOT NULL,
  `body` text,
  `summary` text,
  `category` varchar(128) DEFAULT NULL,
  `tags` json DEFAULT NULL,
  `source_type` varchar(64) DEFAULT NULL,
  `source_platform` varchar(128) DEFAULT NULL,
  `source_url` varchar(1000) DEFAULT NULL,
  `media_type` varchar(64) DEFAULT NULL,
  `extra_meta` json DEFAULT NULL,
  `capabilities` json DEFAULT NULL,
  `source_raw_item_id` char(36) DEFAULT NULL,
  `source_draft_id` char(36) DEFAULT NULL,
  `source_ref_type` varchar(64) DEFAULT NULL,
  `source_ref_id` char(36) DEFAULT NULL,
  `importance` float DEFAULT NULL,
  `status` varchar(32) DEFAULT NULL COMMENT 'active/archived',
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_personal_asset_media_type` (`media_type`),
  KEY `ix_personal_asset_user_id` (`user_id`),
  KEY `ix_personal_asset_source_type` (`source_type`),
  KEY `ix_personal_asset_asset_kind` (`asset_kind`),
  KEY `ix_personal_asset_category` (`category`),
  KEY `ix_personal_asset_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `personal_asset`
--

LOCK TABLES `personal_asset` WRITE;
/*!40000 ALTER TABLE `personal_asset` DISABLE KEYS */;
/*!40000 ALTER TABLE `personal_asset` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `personal_asset_item`
--

DROP TABLE IF EXISTS `personal_asset_item`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `personal_asset_item` (
  `id` char(36) NOT NULL,
  `user_id` char(36) NOT NULL,
  `raw_text` text NOT NULL,
  `raw_title` varchar(255) DEFAULT NULL,
  `raw_source_type` varchar(64) DEFAULT NULL,
  `raw_source_platform` varchar(128) DEFAULT NULL,
  `raw_source_url` varchar(1000) DEFAULT NULL,
  `raw_author` varchar(255) DEFAULT NULL,
  `raw_captured_at` datetime DEFAULT NULL,
  `raw_tags` json DEFAULT NULL,
  `raw_metadata` json DEFAULT NULL,
  `raw_keywords` json DEFAULT NULL,
  `keyword_index_text` text,
  `raw_embedding_ref` varchar(255) DEFAULT NULL,
  `raw_embedding_model` varchar(128) DEFAULT NULL,
  `raw_embedding_status` varchar(32) DEFAULT NULL,
  `raw_embedding_updated_at` datetime DEFAULT NULL,
  `asset_kind` varchar(64) DEFAULT NULL,
  `title` varchar(255) NOT NULL,
  `body` text,
  `rewritten_content` text,
  `summary` text,
  `category` varchar(128) DEFAULT NULL,
  `tags` json DEFAULT NULL,
  `extracts` json DEFAULT NULL,
  `suggested_relations` json DEFAULT NULL,
  `suggested_extensions` json DEFAULT NULL,
  `confidence` json DEFAULT NULL,
  `rationale` text,
  `source_type` varchar(64) DEFAULT NULL,
  `source_platform` varchar(128) DEFAULT NULL,
  `source_url` varchar(1000) DEFAULT NULL,
  `media_type` varchar(64) DEFAULT NULL,
  `extra_meta` json DEFAULT NULL,
  `capabilities` json DEFAULT NULL,
  `source_ref_type` varchar(64) DEFAULT NULL,
  `source_ref_id` char(36) DEFAULT NULL,
  `importance` float DEFAULT NULL,
  `status` varchar(32) DEFAULT NULL COMMENT 'pending_review/confirmed/rejected/archived',
  `reviewed_at` datetime DEFAULT NULL,
  `confirmed_at` datetime DEFAULT NULL,
  `edited_at` datetime DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_personal_asset_item_source_type` (`source_type`),
  KEY `ix_personal_asset_item_raw_source_type` (`raw_source_type`),
  KEY `ix_personal_asset_item_status` (`status`),
  KEY `ix_personal_asset_item_raw_embedding_status` (`raw_embedding_status`),
  KEY `ix_personal_asset_item_asset_kind` (`asset_kind`),
  KEY `ix_personal_asset_item_category` (`category`),
  KEY `ix_personal_asset_item_media_type` (`media_type`),
  KEY `ix_personal_asset_item_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `personal_asset_item`
--

LOCK TABLES `personal_asset_item` WRITE;
/*!40000 ALTER TABLE `personal_asset_item` DISABLE KEYS */;
/*!40000 ALTER TABLE `personal_asset_item` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `personal_asset_unit`
--

DROP TABLE IF EXISTS `personal_asset_unit`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `personal_asset_unit` (
  `id` char(36) NOT NULL,
  `user_id` char(36) NOT NULL,
  `title` varchar(255) NOT NULL,
  `content` text,
  `summary` text,
  `category` varchar(128) DEFAULT NULL,
  `tags` json DEFAULT NULL,
  `source_asset_ids` json DEFAULT NULL,
  `outline` json DEFAULT NULL,
  `confidence` json DEFAULT NULL,
  `rationale` text,
  `status` varchar(32) DEFAULT NULL COMMENT 'pending_review/confirmed/rejected',
  `confirmed_at` datetime DEFAULT NULL,
  `edited_at` datetime DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_personal_asset_unit_category` (`category`),
  KEY `ix_personal_asset_unit_user_id` (`user_id`),
  KEY `ix_personal_asset_unit_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `personal_asset_unit`
--

LOCK TABLES `personal_asset_unit` WRITE;
/*!40000 ALTER TABLE `personal_asset_unit` DISABLE KEYS */;
/*!40000 ALTER TABLE `personal_asset_unit` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `personal_knowledge_unit`
--

DROP TABLE IF EXISTS `personal_knowledge_unit`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `personal_knowledge_unit` (
  `id` char(36) NOT NULL,
  `user_id` char(36) NOT NULL,
  `source_kind` varchar(64) NOT NULL COMMENT 'document_chunk/personal_asset_item',
  `source_id` char(36) NOT NULL,
  `unit_type` varchar(64) DEFAULT NULL,
  `statement` text NOT NULL,
  `normalized_statement` text NOT NULL,
  `normalized_statement_hash` varchar(64) NOT NULL,
  `subject` varchar(255) DEFAULT NULL,
  `predicate` varchar(255) DEFAULT NULL,
  `object` text,
  `polarity` varchar(32) DEFAULT NULL,
  `modality` varchar(64) DEFAULT NULL,
  `domains` json DEFAULT NULL,
  `entities` json DEFAULT NULL,
  `concepts` json DEFAULT NULL,
  `keywords` json DEFAULT NULL,
  `scope` json DEFAULT NULL,
  `conditions` json DEFAULT NULL,
  `evidence_span` text,
  `confidence` float DEFAULT NULL,
  `llm_model` varchar(128) DEFAULT NULL,
  `embedding_ref` varchar(255) DEFAULT NULL,
  `embedding_model` varchar(128) DEFAULT NULL,
  `embedding_status` varchar(32) DEFAULT NULL,
  `status` varchar(32) DEFAULT NULL COMMENT 'active/merged/deprecated/rejected',
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_pku_source_normalized` (`user_id`,`source_kind`,`source_id`,`unit_type`,`normalized_statement_hash`),
  KEY `ix_personal_knowledge_unit_normalized_statement_hash` (`normalized_statement_hash`),
  KEY `ix_personal_knowledge_unit_modality` (`modality`),
  KEY `ix_personal_knowledge_unit_source_kind` (`source_kind`),
  KEY `ix_personal_knowledge_unit_embedding_status` (`embedding_status`),
  KEY `ix_pku_source` (`source_kind`,`source_id`),
  KEY `ix_personal_knowledge_unit_source_id` (`source_id`),
  KEY `ix_personal_knowledge_unit_user_id` (`user_id`),
  KEY `ix_personal_knowledge_unit_polarity` (`polarity`),
  KEY `ix_personal_knowledge_unit_status` (`status`),
  KEY `ix_personal_knowledge_unit_unit_type` (`unit_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `personal_knowledge_unit`
--

LOCK TABLES `personal_knowledge_unit` WRITE;
/*!40000 ALTER TABLE `personal_knowledge_unit` DISABLE KEYS */;
/*!40000 ALTER TABLE `personal_knowledge_unit` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `pku_canonical_link`
--

DROP TABLE IF EXISTS `pku_canonical_link`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `pku_canonical_link` (
  `id` char(36) NOT NULL,
  `user_id` char(36) NOT NULL,
  `pku_id` char(36) NOT NULL,
  `canonical_id` char(36) NOT NULL,
  `relation_type` varchar(64) DEFAULT NULL,
  `role` varchar(64) DEFAULT NULL,
  `confidence` float DEFAULT NULL,
  `reason` text,
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_pku_ckp_relation` (`pku_id`,`canonical_id`,`relation_type`),
  KEY `ix_pku_canonical_link_relation_type` (`relation_type`),
  KEY `ix_pku_canonical_link_role` (`role`),
  KEY `ix_pku_canonical_link_user_id` (`user_id`),
  KEY `ix_pku_canonical_link_canonical_id` (`canonical_id`),
  KEY `ix_pku_canonical_link_pku_id` (`pku_id`),
  CONSTRAINT `pku_canonical_link_ibfk_1` FOREIGN KEY (`pku_id`) REFERENCES `personal_knowledge_unit` (`id`) ON DELETE CASCADE,
  CONSTRAINT `pku_canonical_link_ibfk_2` FOREIGN KEY (`canonical_id`) REFERENCES `canonical_knowledge_point` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `pku_canonical_link`
--

LOCK TABLES `pku_canonical_link` WRITE;
/*!40000 ALTER TABLE `pku_canonical_link` DISABLE KEYS */;
/*!40000 ALTER TABLE `pku_canonical_link` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `pku_relation`
--

DROP TABLE IF EXISTS `pku_relation`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `pku_relation` (
  `id` char(36) NOT NULL,
  `user_id` char(36) NOT NULL,
  `source_pku_id` char(36) NOT NULL,
  `target_pku_id` char(36) NOT NULL,
  `relation_type` varchar(64) DEFAULT NULL,
  `confidence` float DEFAULT NULL,
  `reason` text,
  `source_kind` varchar(64) DEFAULT NULL,
  `source_id` char(36) DEFAULT NULL,
  `llm_model` varchar(128) DEFAULT NULL,
  `metadata` json DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_pku_relation` (`source_pku_id`,`target_pku_id`,`relation_type`),
  KEY `ix_pku_relation_source_pku_id` (`source_pku_id`),
  KEY `ix_pku_relation_user_id` (`user_id`),
  KEY `ix_pku_relation_relation_type` (`relation_type`),
  KEY `ix_pku_relation_source_kind` (`source_kind`),
  KEY `ix_pku_relation_target_pku_id` (`target_pku_id`),
  KEY `ix_pku_relation_source_id` (`source_id`),
  CONSTRAINT `pku_relation_ibfk_1` FOREIGN KEY (`source_pku_id`) REFERENCES `personal_knowledge_unit` (`id`) ON DELETE CASCADE,
  CONSTRAINT `pku_relation_ibfk_2` FOREIGN KEY (`target_pku_id`) REFERENCES `personal_knowledge_unit` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `pku_relation`
--

LOCK TABLES `pku_relation` WRITE;
/*!40000 ALTER TABLE `pku_relation` DISABLE KEYS */;
/*!40000 ALTER TABLE `pku_relation` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `wiki_concept`
--

DROP TABLE IF EXISTS `wiki_concept`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `wiki_concept` (
  `id` char(36) NOT NULL,
  `document_id` char(36) NOT NULL,
  `name` varchar(512) NOT NULL COMMENT 'Concept name (Chinese)',
  `type` varchar(32) DEFAULT NULL COMMENT 'concept/technique/source/claim/artifact',
  `description` text COMMENT 'Specific factual description',
  `aliases` varchar(1024) DEFAULT NULL COMMENT 'Aliases, comma separated',
  `group_name` varchar(256) DEFAULT NULL COMMENT 'LLM assigned group name',
  `category` varchar(128) DEFAULT NULL COMMENT 'Category',
  `created_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `document_id` (`document_id`),
  KEY `ix_wiki_concept_group_name` (`group_name`),
  CONSTRAINT `wiki_concept_ibfk_1` FOREIGN KEY (`document_id`) REFERENCES `wiki_document` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `wiki_concept`
--

LOCK TABLES `wiki_concept` WRITE;
/*!40000 ALTER TABLE `wiki_concept` DISABLE KEYS */;
/*!40000 ALTER TABLE `wiki_concept` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `wiki_document`
--

DROP TABLE IF EXISTS `wiki_document`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `wiki_document` (
  `id` char(36) NOT NULL,
  `file_id` char(36) NOT NULL,
  `status` varchar(20) DEFAULT NULL COMMENT 'pending/processing/completed/failed',
  `extract_stage` varchar(50) DEFAULT NULL COMMENT 'Current stage name',
  `progress_current` int DEFAULT NULL,
  `progress_total` int DEFAULT NULL,
  `user_id` char(36) DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `file_id` (`file_id`),
  CONSTRAINT `wiki_document_ibfk_1` FOREIGN KEY (`file_id`) REFERENCES `knowledge_file` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `wiki_document`
--

LOCK TABLES `wiki_document` WRITE;
/*!40000 ALTER TABLE `wiki_document` DISABLE KEYS */;
/*!40000 ALTER TABLE `wiki_document` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `wiki_extraction_log`
--

DROP TABLE IF EXISTS `wiki_extraction_log`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `wiki_extraction_log` (
  `id` char(36) NOT NULL,
  `document_id` char(36) NOT NULL,
  `stage` varchar(50) DEFAULT NULL COMMENT 'Stage name',
  `message` text COMMENT 'Log content',
  `status` varchar(16) DEFAULT NULL COMMENT 'info/warning/error',
  `progress_current` int DEFAULT NULL,
  `progress_total` int DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `document_id` (`document_id`),
  CONSTRAINT `wiki_extraction_log_ibfk_1` FOREIGN KEY (`document_id`) REFERENCES `wiki_document` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `wiki_extraction_log`
--

LOCK TABLES `wiki_extraction_log` WRITE;
/*!40000 ALTER TABLE `wiki_extraction_log` DISABLE KEYS */;
/*!40000 ALTER TABLE `wiki_extraction_log` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `wiki_image`
--

DROP TABLE IF EXISTS `wiki_image`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `wiki_image` (
  `id` char(36) NOT NULL,
  `document_id` char(36) NOT NULL,
  `image_index` int DEFAULT NULL COMMENT 'Image sequence (1-based)',
  `storage_path` varchar(500) DEFAULT NULL COMMENT 'Storage path',
  `caption` text COMMENT 'Vision LLM description',
  `mime_type` varchar(100) DEFAULT NULL COMMENT 'MIME type',
  `created_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `document_id` (`document_id`),
  CONSTRAINT `wiki_image_ibfk_1` FOREIGN KEY (`document_id`) REFERENCES `wiki_document` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `wiki_image`
--

LOCK TABLES `wiki_image` WRITE;
/*!40000 ALTER TABLE `wiki_image` DISABLE KEYS */;
/*!40000 ALTER TABLE `wiki_image` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `wiki_knowledge_point`
--

DROP TABLE IF EXISTS `wiki_knowledge_point`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `wiki_knowledge_point` (
  `id` char(36) NOT NULL,
  `document_id` char(36) NOT NULL,
  `title` varchar(512) NOT NULL COMMENT 'Knowledge point title',
  `description` text COMMENT 'Refined description (100-200 chars, Stage 3.5a)',
  `content` text COMMENT 'Structured Markdown article (Stage 3.5b)',
  `category` varchar(128) DEFAULT NULL COMMENT 'Category',
  `tags` varchar(1024) DEFAULT NULL COMMENT 'Tags, comma separated',
  `aliases` varchar(1024) DEFAULT NULL COMMENT 'Aliases, comma separated',
  `group_name` varchar(256) DEFAULT NULL COMMENT 'Group name',
  `status` varchar(16) DEFAULT NULL COMMENT '整理中/已发布',
  `images` text COMMENT 'Associated images JSON: [{''id'':''uuid'',''caption'':''desc''},...]',
  `user_id` char(36) DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `document_id` (`document_id`),
  CONSTRAINT `wiki_knowledge_point_ibfk_1` FOREIGN KEY (`document_id`) REFERENCES `wiki_document` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `wiki_knowledge_point`
--

LOCK TABLES `wiki_knowledge_point` WRITE;
/*!40000 ALTER TABLE `wiki_knowledge_point` DISABLE KEYS */;
/*!40000 ALTER TABLE `wiki_knowledge_point` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `wiki_knowledge_relation`
--

DROP TABLE IF EXISTS `wiki_knowledge_relation`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `wiki_knowledge_relation` (
  `id` char(36) NOT NULL,
  `from_point_id` char(36) NOT NULL,
  `to_point_id` char(36) NOT NULL,
  `type` varchar(64) DEFAULT NULL COMMENT 'implements/extends/optimizes/contradicts/cites/prerequisite_of/trades_off/derived_from',
  `confidence` float DEFAULT NULL COMMENT 'Confidence 0.0~1.0',
  `created_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `from_point_id` (`from_point_id`),
  KEY `to_point_id` (`to_point_id`),
  CONSTRAINT `wiki_knowledge_relation_ibfk_1` FOREIGN KEY (`from_point_id`) REFERENCES `wiki_knowledge_point` (`id`) ON DELETE CASCADE,
  CONSTRAINT `wiki_knowledge_relation_ibfk_2` FOREIGN KEY (`to_point_id`) REFERENCES `wiki_knowledge_point` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `wiki_knowledge_relation`
--

LOCK TABLES `wiki_knowledge_relation` WRITE;
/*!40000 ALTER TABLE `wiki_knowledge_relation` DISABLE KEYS */;
/*!40000 ALTER TABLE `wiki_knowledge_relation` ENABLE KEYS */;
UNLOCK TABLES;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-07-31 17:02:05
