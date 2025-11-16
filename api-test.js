/**
 * @NApiVersion 2.1
 * @NScriptType Restlet
 */
define(['N/https', 'N/log'], (https, log) => {

    const FEASURE_URL = 'https://feasure-api.onrender.com/ai';

    function post(context) {
        try {
            const prompt = (context && context.prompt) || 'Hello from NetSuite';

            const response = https.post({
                url: FEASURE_URL,
                headers: {
                    'Content-Type': 'application/json',
                    // later: add a shared secret so only your NetSuite can call Feasure
                    // 'x-feasure-key': 'YOUR_SHARED_SECRET'
                },
                body: JSON.stringify({ prompt: prompt })
            });

            log.debug('Feasure status', response.code);
            log.debug('Feasure raw response', response.body);

            let parsed;
            try {
                parsed = JSON.parse(response.body);
            } catch (e) {
                log.error('Feasure JSON parse error', e);
                return { success: false, error: 'Invalid JSON from Feasure', raw: response.body };
            }

            return {
                success: true,
                reply: parsed.reply || parsed.output || parsed,
                status: response.code
            };

        } catch (e) {
            log.error('Feasure RESTlet error', e);
            return {
                success: false,
                error: e.message || e.toString()
            };
        }
    }

    return { post };
});
