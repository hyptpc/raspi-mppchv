function fetchLogDataAndFillTable() {
    $.getJSON('/_fetch_log', function(data) {
        // テーブルのtbodyを空にする
        $('#log-table tbody').empty();
        // 結果をテーブルに追加
        $.each(data.logs, function(index, log) {
            var row = $('<tr>');
            row.append($('<td>').text(log.time));
            row.append($('<td>').text(log.module_id));
            row.append($('<td>').text(log.cmd_tx));
            row.append($('<td>').text(log.cmd_rx));
            row.append($('<td>').addClass(log.status).text(log.status));
            $('#log-table tbody').append(row);
        });
    }).fail(function() {
        alert('データの取得に失敗しました');
    });
}

$(document).ready(function() {
    $('button.apply-button').on('click', function() {
        var moduleId = $(this).data('module-id');
        var name     = $(this).attr('name');

        // 対応するテーブルのtbodyを特定する
        var hvForm = $('#hv-form-' + moduleId);
        var hvValue = hvForm.val();

        if (hvValue === "") {
            alert('エラー: HVの値を入力してください');
        } else if (confirm("module" + moduleId + 'のhvを' + hvValue + "にしますか？")) {
            $.getJSON('/_change_hv', { module_id: moduleId, hv_value: hvValue, name: name }, function(data) {
                var statusCode = data.status_code;
                fetchLogDataAndFillTable();
                if (statusCode == 1) {
                    alert('失敗');
                } else if ( statusCode == 2 ) {
                    alert('Error: Out of Range');
                }
            });
        }
        hvForm.val('');
    });
});