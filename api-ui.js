/**
 * @NApiVersion 2.1
 * @NScriptType Suitelet
 */
define(['N/ui/serverWidget', 'N/https', 'N/log', 'N/search'],
    (serverWidget, https, log, search) => {

    const FEASURE_URL = 'https://feasure-api.onrender.com/ai';

    function buildForm(options) {
        const {
            promptValue = '',
            responseText = '',
            previewRows = [],
            previewColumns = []
        } = options || {};

        const form = serverWidget.createForm({
            title: 'Feasure Assistant'
        });

        // --- Prompt field ---
        const promptField = form.addField({
            id: 'custpage_feasure_prompt',
            type: serverWidget.FieldType.TEXTAREA,
            label: 'Ask Feasure'
        });
        promptField.updateLayoutType({
            layoutType: serverWidget.FieldLayoutType.OUTSIDEABOVE
        });
        promptField.updateDisplaySize({
            height: 4,
            width: 80
        });
        promptField.defaultValue = promptValue;

        // --- Response / explanation field ---
        const respField = form.addField({
            id: 'custpage_feasure_response',
            type: serverWidget.FieldType.TEXTAREA,
            label: 'Response / Explanation'
        });
        respField.updateLayoutType({
            layoutType: serverWidget.FieldLayoutType.OUTSIDEABOVE
        });
        respField.updateDisplaySize({
            height: 10,
            width: 80
        });
        respField.defaultValue = responseText;

        // --- Preview sublist for ad-hoc search results (if any) ---
        if (previewColumns && previewColumns.length > 0) {
            const sublist = form.addSublist({
                id: 'custpage_feasure_preview',
                type: serverWidget.SublistType.LIST,
                label: 'Feasure Search Preview (first 20 rows)'
            });

            // Add one column per spec column
            previewColumns.forEach(colId => {
                sublist.addField({
                    id: 'custpage_col_' + colId.replace(/[^a-z0-9_]/gi, '_'),
                    type: serverWidget.FieldType.TEXT,
                    label: colId
                });
            });

            for (let i = 0; i < previewRows.length; i++) {
                const row = previewRows[i];
                previewColumns.forEach(colId => {
                    const fieldId = 'custpage_col_' + colId.replace(/[^a-z0-9_]/gi, '_');
                    const value = row[colId] != null ? String(row[colId]) : '';
                    if (value) {
                        sublist.setSublistValue({
                            id: fieldId,
                            line: i,
                            value: value
                        });
                    }
                });
            }
        }

        form.addSubmitButton({
            label: 'Ask Feasure'
        });

        return form;
    }

    function onRequest(context) {
        if (context.request.method === 'GET') {
            const form = buildForm({});
            context.response.writePage(form);
            return;
        }

        const req = context.request;
        const prompt = req.parameters.custpage_feasure_prompt || '';

        let replyText = '';
        let previewRows = [];
        let previewColumns = [];

        try {
            const apiResponse = https.post({
                url: FEASURE_URL,
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    prompt: prompt
                    // backend will route via intent router (chat vs search_builder)
                })
            });

            log.debug('Feasure API status', apiResponse.code);
            log.debug('Feasure API body', apiResponse.body);

            if (apiResponse.code !== 200) {
                replyText = 'Feasure API error: ' + apiResponse.body;
            } else {
                const parsed = JSON.parse(apiResponse.body);

                if (parsed.mode === 'search_builder' && parsed.search_spec) {
                    const spec = parsed.search_spec;
                    log.debug('Feasure search spec', JSON.stringify(spec));

                    // 1) Create an ad-hoc search (NOT saved)
                    const searchObj = search.create({
                        type: spec.recordType,
                        filters: spec.filters,
                        columns: spec.columns
                    });

                    // 2) Explanation from backend (if present)
                    replyText = parsed.explanation ||
                        'Ad-hoc search created. Showing first 20 results.';

                    // 3) Run search and build preview rows
                    const results = searchObj.run().getRange({
                        start: 0,
                        end: 20
                    });

                    previewColumns = spec.columns.slice(); // copy
                    previewRows = results.map(result => {
                        const row = {};
                        previewColumns.forEach(colId => {
                            row[colId] = result.getValue({ name: colId });
                        });
                        return row;
                    });

                } else if (parsed.mode === 'chat') {
                    // Plain chat / explanation from Feasure
                    replyText = parsed.reply || apiResponse.body;

                } else {
                    replyText = 'Unexpected Feasure response format.\n\nRaw:\n' +
                        apiResponse.body;
                }
            }

        } catch (e) {
            log.error('Feasure HTTPS or search error', e);
            replyText = 'Error calling Feasure or running search:\n' + e.toString();
        }

        const form = buildForm({
            promptValue: prompt,
            responseText: replyText,
            previewRows: previewRows,
            previewColumns: previewColumns
        });

        context.response.writePage(form);
    }

    return { onRequest };
});
