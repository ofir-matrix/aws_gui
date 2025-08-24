(function() {
	function parseIp(ip) {
		if (!ip) return -1;
		var parts = String(ip).split('.');
		if (parts.length !== 4) return -1;
		var n = 0;
		for (var i = 0; i < 4; i++) {
			var v = parseInt(parts[i], 10);
			if (isNaN(v)) return -1;
			n = (n << 8) + v;
		}
		return n >>> 0;
	}

	function compare(a, b, type) {
		if (type === 'ip') {
			return parseIp(a) - parseIp(b);
		}
		// default string compare, case-insensitive
		a = (a || '').toString().toLowerCase();
		b = (b || '').toString().toLowerCase();
		if (a < b) return -1;
		if (a > b) return 1;
		return 0;
	}

	function setupTableSorting(table) {
		var thead = table.querySelector('thead');
		if (!thead) return;
		var headers = thead.querySelectorAll('th.sortable');
		headers.forEach(function(th, index) {
			th.addEventListener('click', function() {
				var type = th.getAttribute('data-type') || 'string';
				var tbody = table.querySelector('tbody');
				var rows = Array.from(tbody.querySelectorAll('tr'));
				var ascending = !th.classList.contains('sorted-asc');

				rows.sort(function(rowA, rowB) {
					var a = rowA.children[index].innerText.trim();
					var b = rowB.children[index].innerText.trim();
					return ascending ? compare(a, b, type) : -compare(a, b, type);
				});

				// clear existing sort classes
				headers.forEach(function(h) { h.classList.remove('sorted-asc', 'sorted-desc'); });
				th.classList.add(ascending ? 'sorted-asc' : 'sorted-desc');

				rows.forEach(function(row) { tbody.appendChild(row); });
			});
		});
	}

	document.addEventListener('DOMContentLoaded', function() {
		document.querySelectorAll('table.instances').forEach(setupTableSorting);
	});
})();

