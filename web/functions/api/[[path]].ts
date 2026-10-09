import { proxy } from "../_lib/proxy";

export const onRequest = async (context: { request: Request }): Promise<Response> => proxy(context.request);
