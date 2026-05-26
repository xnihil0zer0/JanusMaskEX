window.loadAstGraph = function() {
    const container = document.getElementById('graph-canvas');
    if (!container) return;

    // Reset container HTML to show loading status
    container.innerHTML = '<div style="display: flex; align-items: center; justify-content: center; height: 100%; color: var(--text-secondary);">Generating graph mapping...</div>';

    fetch('/api/ast_graph')
        .then(res => res.json())
        .then(graphData => {
            if (!graphData.nodes || graphData.nodes.length === 0) {
                container.innerHTML = '<div style="display: flex; align-items: center; justify-content: center; height: 100%; color: var(--text-secondary);">No nodes found. Run tasks to populate workspace modules.</div>';
                return;
            }

            container.innerHTML = '';

            // Assign colors based on node type
            const nodes = graphData.nodes.map(node => {
                let color = '#2b7ce9'; // default
                let shape = 'dot';
                
                if (node.type === 'file') {
                    color = { background: '#00f0ff', border: '#0055ff', highlight: { background: '#33f5ff', border: '#0055ff' } };
                    shape = 'diamond';
                } else if (node.type === 'class') {
                    color = { background: '#00ff66', border: '#00aa33', highlight: { background: '#33ff88', border: '#00aa33' } };
                    shape = 'dot';
                } else if (node.type === 'function') {
                    color = { background: '#ffb700', border: '#aa7700', highlight: { background: '#ffcc33', border: '#aa7700' } };
                    shape = 'triangle';
                }
                
                return {
                    id: node.id,
                    label: node.label,
                    shape: shape,
                    color: color,
                    font: { color: '#f5f6f8', size: 11, face: 'Inter' },
                    title: `${node.type.toUpperCase()}: ${node.label}`,
                    customData: node
                };
            });

            const edges = graphData.edges.map(edge => {
                return {
                    from: edge.from,
                    to: edge.to,
                    arrows: 'to',
                    color: { color: 'rgba(255, 255, 255, 0.12)', highlight: '#00f0ff' }
                };
            });

            const data = {
                nodes: new vis.DataSet(nodes),
                edges: new vis.DataSet(edges)
            };

            const options = {
                nodes: {
                    scaling: {
                        min: 10,
                        max: 30
                    }
                },
                edges: {
                    smooth: {
                        type: 'cubicBezier',
                        forceDirection: 'vertical',
                        roundness: 0.4
                    }
                },
                physics: {
                    solver: 'forceAtlas2Based',
                    forceAtlas2Based: {
                        gravitationalConstant: -50,
                        centralGravity: 0.01,
                        springLength: 100,
                        springConstant: 0.08
                    },
                    maxVelocity: 50,
                    minVelocity: 0.1,
                    stabilization: {
                        iterations: 100
                    }
                }
            };

            const network = new vis.Network(container, data, options);

            // Handle clicking a node to inspect it
            network.on("click", function(params) {
                if (params.nodes.length > 0) {
                    const nodeId = params.nodes[0];
                    const clickedNode = nodes.find(n => n.id === nodeId);
                    if (clickedNode && clickedNode.customData) {
                        const info = clickedNode.customData;
                        const inspector = document.getElementById("inspector-panel");
                        
                        let extraDetails = "";
                        if (info.type === 'file') {
                            extraDetails = `
                            <div style="margin-top: 0.75rem;">
                                <span style="color: var(--text-secondary);">Relative Path:</span>
                                <div style="color: var(--accent-green); margin-top: 0.25rem;">${info.path}</div>
                            </div>`;
                        } else if (info.type === 'class') {
                            extraDetails = `
                            <div style="margin-top: 0.75rem;">
                                <span style="color: var(--text-secondary);">Scope:</span>
                                <div style="color: var(--accent-yellow); margin-top: 0.25rem;">Class Definition</div>
                            </div>`;
                        } else if (info.type === 'function') {
                            extraDetails = `
                            <div style="margin-top: 0.75rem;">
                                <span style="color: var(--text-secondary);">Scope:</span>
                                <div style="color: var(--accent-blue); margin-top: 0.25rem;">Function Definition</div>
                            </div>`;
                        }

                        inspector.innerHTML = `
                            <div>
                                <h3 style="color: var(--accent-blue); font-family: 'Orbitron', sans-serif; font-size: 1rem; border-bottom: 1px solid var(--border-color); padding-bottom: 0.5rem; margin-bottom: 1rem;">
                                    ${info.label}
                                </h3>
                                <div style="display: flex; flex-direction: column; gap: 0.75rem;">
                                    <div>
                                        <span style="color: var(--text-secondary);">Node Type:</span>
                                        <span style="text-transform: uppercase; font-weight: bold; margin-left: 0.5rem;" class="${info.type === 'file' ? 'text-blue' : info.type === 'class' ? 'text-green' : 'text-yellow'}">
                                            ${info.type}
                                        </span>
                                    </div>
                                    <div>
                                        <span style="color: var(--text-secondary);">Identifier:</span>
                                        <div style="word-break: break-all; margin-top: 0.25rem;">${info.id}</div>
                                    </div>
                                    ${extraDetails}
                                </div>
                            </div>
                        `;
                    }
                }
            });
        })
        .catch(err => {
            console.error("Failed to load AST graph", err);
            container.innerHTML = `<div class="text-center p-4 text-red" style="color: var(--accent-red)">Failed to generate AST graph: ${err}</div>`;
        });
};

// Initial load if tab is active
window.addEventListener('load', () => {
    const tabGraph = document.getElementById('tab-graph');
    if (tabGraph && tabGraph.classList.contains('active')) {
        window.loadAstGraph();
    }
});
