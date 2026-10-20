(() => {
  if (!window.Chart) return;
  const forecast = document.getElementById('forecast-chart-data');
  if (forecast) { const d = JSON.parse(forecast.textContent); new Chart(document.getElementById('forecast-history'), {type:'line', data:{labels:d.labels,datasets:[{label:'Historical units',data:d.actual,borderColor:'#0b8f8c',tension:.3},{label:'Predicted next month',data:d.prediction,borderColor:'#f4a261',pointRadius:6}]}}); return; }
  const node=document.getElementById('chart-data'); if(!node)return; const d=JSON.parse(node.textContent); const draw=(id,type,labels,datasets)=>{const e=document.getElementById(id);if(e)new Chart(e,{type,data:{labels,datasets},options:{responsive:true,maintainAspectRatio:false}})};
  draw('monthly','line',d.monthly.labels,[{label:'Units sold',data:d.monthly.data,borderColor:'#0b8f8c'}]); draw('categories','doughnut',d.categories.labels,[{data:d.categories.data}]); draw('warehouse','bar',d.warehouse.labels,[{label:'Inventory on hand',data:d.warehouse.stock},{label:'Reorder level',data:d.warehouse.reorder}]); draw('accuracy','line',d.accuracy.labels,[{label:'Actual sales',data:d.accuracy.actual},{label:'Predicted sales',data:d.accuracy.predicted}]);
})();
