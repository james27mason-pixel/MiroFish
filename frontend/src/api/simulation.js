import service from './index'

/**
 * 创建模拟
 * @param {Object} data - { project_id, graph_id?, enable_twitter?, enable_reddit? }
 */
export const createSimulation = (data) => {
  return service.post('/api/simulation/create', data)
}

/**
 * 准备模拟环境（异步任务）
 * @param {Object} data - { simulation_id, entity_types?, use_llm_for_profiles?, parallel_profile_count?, force_regenerate? }
 */
export const prepareSimulation = (data) => {
  return service.post('/api/simulation/prepare', data)
}

/**
 * 查询准备任务进度
 * @param {Object} data - { task_id?, simulation_id? }
 */
export const getPrepareStatus = (data) => {
  return service.post('/api/simulation/prepare/status', data)
}

/** 获取模拟状态 */
export const getSimulation = (simulationId) => {
  return service.get(`/api/simulation/${simulationId}`)
}

export const getSimulationProfiles = (simulationId, platform) => {
  const params = platform ? { platform } : {}
  return service.get(`/api/simulation/${simulationId}/profiles`, { params })
}

export const getSimulationProfilesRealtime = (simulationId, platform) => {
  const params = platform ? { platform } : {}
  return service.get(`/api/simulation/${simulationId}/profiles/realtime`, { params })
}

export const getSimulationConfig = (simulationId) => {
  return service.get(`/api/simulation/${simulationId}/config`)
}

export const getSimulationConfigRealtime = (simulationId) => {
  return service.get(`/api/simulation/${simulationId}/config/realtime`)
}

export const listSimulations = (projectId) => {
  const params = projectId ? { project_id: projectId } : {}
  return service.get('/api/simulation/list', { params })
}

/**
 * Start the dual-world simulation.
 *
 * Render deployments previously reached the backend with an invalid/stale
 * platform value and failed before round 1. Step 3 is intentionally the
 * parallel Twitter+Reddit simulation, so normalize the wire value here rather
 * than trusting stale component/browser state.
 *
 * Dynamic Zep graph-memory writes are temporarily disabled at launch. The
 * source GraphRAG graph and prepared personas/config remain intact; simulation
 * actions are still recorded normally. This avoids an optional graph-memory
 * updater becoming a synchronous launch blocker on the free Render service.
 */
export const startSimulation = (data) => {
  const payload = {
    ...data,
    platform: 'parallel',
    enable_graph_memory_update: false
  }
  return service.post('/api/simulation/start', payload)
}

export const stopSimulation = (data) => {
  return service.post('/api/simulation/stop', data)
}

export const getRunStatus = (simulationId) => {
  return service.get(`/api/simulation/${simulationId}/run-status`)
}

export const getRunStatusDetail = (simulationId) => {
  return service.get(`/api/simulation/${simulationId}/run-status/detail`)
}

export const getSimulationPosts = (simulationId, platform, limit = 50, offset = 0) => {
  const params = { limit, offset }
  if (platform) params.platform = platform
  return service.get(`/api/simulation/${simulationId}/posts`, { params })
}

export const getSimulationTimeline = (simulationId, startRound = 0, endRound = null) => {
  const params = { start_round: startRound }
  if (endRound !== null) params.end_round = endRound
  return service.get(`/api/simulation/${simulationId}/timeline`, { params })
}

export const getAgentStats = (simulationId) => {
  return service.get(`/api/simulation/${simulationId}/agent-stats`)
}

export const getSimulationActions = (simulationId, params = {}) => {
  return service.get(`/api/simulation/${simulationId}/actions`, { params })
}

export const closeSimulationEnv = (data) => {
  return service.post('/api/simulation/close-env', data)
}

export const getEnvStatus = (data) => {
  return service.post('/api/simulation/env-status', data)
}

export const interviewAgents = (data) => {
  return service.post('/api/simulation/interview/batch', data)
}

export const getSimulationHistory = (limit = 20) => {
  return service.get('/api/simulation/history', { params: { limit } })
}
