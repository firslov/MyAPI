// Load and display LLM servers and models
async function loadConfigs() {
    try {
        // Load LLM servers
        const serversResponse = await fetch('/get-llm-servers');
        const servers = await serversResponse.json();
        const serversTable = document.getElementById('llmServersTable');
        serversTable.innerHTML = '';

        for (const [url, config] of Object.entries(servers)) {
            const models = Object.entries(config.model || {}).map(([k, v]) => {
                const statusClass = v.status ? 'text-green-500' : 'text-red-500';
                const statusIcon = v.status ? 'fa-check-circle' : 'fa-times-circle';
                const statusTitle = v.status ? 'Active' : 'Inactive';
                const statusClick = `toggleModelStatus('${encodeURIComponent(url)}','${encodeURIComponent(k)}',${v.status})`;
                return [
                    '<div class="flex items-center justify-between py-1">',
                    '<span>' + k + '→' + v.name + '</span>',
                    '<div class="flex items-center space-x-2">',
                    '<span class="text-xs text-gray-500">' + v.reqs.toString() + ' reqs</span>',
                    '<i class="fas ' + statusIcon + ' ' + statusClass + '" title="' + statusTitle.toString() + '" onclick="' + statusClick + '"></i>',
                    '</div>',
                    '</div>'
                ].join('');
            }).join('');
            const row = document.createElement('tr');
            row.className = 'hover:bg-gray-50 transition-colors';
            row.innerHTML = '<td class="px-2 md:px-4 py-2 md:py-3 text-xs md:text-sm text-gray-700">' + url + '</td>' +
                '<td class="px-2 md:px-4 py-2 md:py-3 text-xs md:text-sm text-gray-700">' + (config.device || 'N/A') + '</td>' +
                '<td class="px-2 md:px-4 py-2 md:py-3 text-xs md:text-sm text-gray-700"><div class="space-y-1">' + models + '</div></td>' +
                '<td class="px-2 md:px-4 py-2 md:py-3 text-xs md:text-sm space-x-2">' +
                '<button onclick="showEditServerModal(\'' + encodeURIComponent(url) + '\')" class="text-indigo-600 hover:text-indigo-800" title="Edit">' +
                '<i class="fas fa-edit"></i></button>' +
                '<button onclick="deleteServer(\'' + encodeURIComponent(url) + '\')" class="text-red-600 hover:text-red-800" title="Delete">' +
                '<i class="fas fa-trash"></i></button></td>';
            serversTable.appendChild(row);
        }

        // Load serve models
        const modelsResponse = await fetch('/get-models');
        const modelsData = await modelsResponse.json();
        const modelsTable = document.getElementById('serveModelsTable');
        modelsTable.innerHTML = '';

        for (const model of modelsData.models || []) {
            const row = document.createElement('tr');
            row.className = 'hover:bg-gray-50 transition-colors';
            row.innerHTML = '<td class="px-2 md:px-4 py-2 md:py-3 text-xs md:text-sm text-gray-700">' + model + '</td>' +
                '<td class="px-2 md:px-4 py-2 md:py-3 text-xs md:text-sm">' +
                '<button onclick="deleteModel(\'' + encodeURIComponent(model) + '\')" class="text-red-600 hover:text-red-800" title="Delete">' +
                '<i class="fas fa-trash"></i></button></td>';
            modelsTable.appendChild(row);
        }
    } catch (error) {
        console.error('Error loading configs:', error);
    }
}

// Server management functions
function showAddServerModal() {
    document.getElementById('addServerModal').style.display = 'flex';
}

function closeAddServerModal() {
    document.getElementById('addServerModal').style.display = 'none';
}

async function addServer() {
    const url = document.getElementById('serverUrl').value;
    const device = document.getElementById('serverDevice').value;
    const apiKey = document.getElementById('serverApiKey').value;
    const models = document.getElementById('serverModels').value;

    if (!url || !device || !models) {
        alert('URL, Device and Models are required');
        return;
    }

    try {
        const response = await fetch('/update-llm-servers', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                action: 'add',
                url,
                config: {
                    device,
                    apikey: apiKey || undefined,
                    model: JSON.parse(models)
                }
            }),
        });

        if (!response.ok) {
            throw new Error('Failed to add server');
        }

        closeAddServerModal();
        loadConfigs();
    } catch (error) {
        alert('Error adding server: ' + error.message);
    }
}

async function deleteServer(url) {
    if (!confirm('Are you sure you want to delete this server?')) {
        return;
    }

    try {
        const response = await fetch('/update-llm-servers', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                action: 'delete',
                url
            }),
        });

        if (!response.ok) {
            throw new Error('Failed to delete server');
        }

        loadConfigs();
    } catch (error) {
        alert('Error deleting server: ' + error.message);
    }
}

// Edit Server Modal
function showEditServerModal(url) {
    document.getElementById('editServerUrl').value = url;
    fetch('/get-llm-servers')
        .then(response => {
            if (!response.ok) throw new Error('Network response was not ok');
            return response.json();
        })
        .then(servers => {
            const decodedUrl = decodeURIComponent(url);
            const config = servers[decodedUrl];
            if (!config) throw new Error('Server config not found');
            
            document.getElementById('editServerDevice').value = config.device || '';
            document.getElementById('editServerApiKey').value = config.apikey || '';
            document.getElementById('editServerModels').value = JSON.stringify(config.model || {}, null, 2);
            document.getElementById('editServerModal').style.display = 'flex';
        })
        .catch(error => {
            console.error('Error loading server details:', error);
            alert('Failed to load server details: ' + error.message);
        });
}

function closeEditServerModal() {
    document.getElementById('editServerModal').style.display = 'none';
}

async function updateServer() {
    const oldUrl = document.getElementById('editServerUrl').value;
    const newUrl = document.getElementById('editServerUrl').value; // Same URL for now
    const device = document.getElementById('editServerDevice').value;
    const apiKey = document.getElementById('editServerApiKey').value;
    const models = document.getElementById('editServerModels').value;

    if (!newUrl || !device || !models) {
        alert('URL, Device and Models are required');
        return;
    }

    try {
        const response = await fetch('/update-llm-servers', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                action: 'update',
                oldUrl,
                url: newUrl,
                config: {
                    device,
                    apikey: apiKey || undefined,
                    model: JSON.parse(models)
                }
            }),
        });

        if (!response.ok) {
            throw new Error('Failed to update server');
        }

        closeEditServerModal();
        loadConfigs();
    } catch (error) {
        alert('Error updating server: ' + error.message);
    }
}

// Toggle model status
async function toggleModelStatus(serverUrl, modelId, currentStatus) {
    try {
        const serversResponse = await fetch('/get-llm-servers');
        const servers = await serversResponse.json();
        const decodedUrl = decodeURIComponent(serverUrl);
        const decodedModel = decodeURIComponent(modelId);
        
        if (!servers[decodedUrl]?.model?.[decodedModel]) {
            throw new Error('Model not found');
        }

        // Update status
        servers[decodedUrl].model[decodedModel].status = !currentStatus;

        const response = await fetch('/update-llm-servers', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                action: 'update',
                oldUrl: decodedUrl,
                url: decodedUrl,
                config: servers[decodedUrl]
            }),
        });

        if (!response.ok) {
            throw new Error('Failed to update model status');
        }

        loadConfigs();
    } catch (error) {
        alert('Error toggling model status: ' + error.message);
    }
}

// Model management functions
function showAddModelModal() {
    document.getElementById('addModelModal').style.display = 'flex';
}

function closeAddModelModal() {
    document.getElementById('addModelModal').style.display = 'none';
}

async function addModel() {
    const model = document.getElementById('modelName').value;

    if (!model) {
        alert('Model name is required');
        return;
    }

    try {
        const response = await fetch('/update-serve-models', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                action: 'add',
                model
            }),
        });

        if (!response.ok) {
            throw new Error('Failed to add model');
        }

        closeAddModelModal();
        loadConfigs();
    } catch (error) {
        alert('Error adding model: ' + error.message);
    }
}

async function deleteModel(model) {
    if (!confirm('Are you sure you want to delete this model?')) {
        return;
    }

    try {
        const response = await fetch('/update-serve-models', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                action: 'delete',
                model
            }),
        });

        if (!response.ok) {
            throw new Error('Failed to delete model');
        }

        loadConfigs();
    } catch (error) {
        alert('Error deleting model: ' + error.message);
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', loadConfigs);

// Original functions
function showEditLimit(apiKey, currentLimit) {
    document.getElementById('editLimitModal').style.display = 'flex';
    document.getElementById('newLimit').value = currentLimit;
    document.getElementById('currentApiKey').value = apiKey;
}

function closeEditModal() {
    document.getElementById('editLimitModal').style.display = 'none';
}

async function updateLimit() {
    const apiKey = document.getElementById('currentApiKey').value;
    const newLimit = parseInt(document.getElementById('newLimit').value);

    if (!newLimit || newLimit <= 0) {
        alert('Please enter a valid limit');
        return;
    }

    try {
        const response = await fetch('/update-api-key-limit', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                api_key: apiKey,
                new_limit: newLimit
            }),
        });

        if (!response.ok) {
            throw new Error('Failed to update limit');
        }

        document.getElementById(`limit_${apiKey}`).textContent = newLimit;
        closeEditModal();
    } catch (error) {
        alert('Error updating limit: ' + error.message);
    }
}

async function resetUsage(apiKey) {
    if (!confirm('Are you sure you want to reset the usage for this API key?')) {
        return;
    }
    try {
        const response = await fetch('/reset-api-key-usage', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ api_key: apiKey }),
        });
        if (!response.ok) {
            throw new Error('Failed to reset usage');
        }
        document.getElementById(`usage_${apiKey}`).textContent = '0';
    } catch (error) {
        alert('Error resetting usage: ' + error.message);
    }
}

async function revokeKey(apiKey) {
    if (!confirm('Are you sure you want to revoke this API key?')) {
        return;
    }
    try {
        const response = await fetch('/revoke-api-key', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ api_key: apiKey }),
        });
        if (!response.ok) {
            throw new Error('Failed to revoke API key');
        }
        window.location.reload();
    } catch (error) {
        alert('Error revoking API key: ' + error.message);
    }
}
