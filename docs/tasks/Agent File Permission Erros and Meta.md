# Agent File Permission Erros and Meta

kio nodes need a meta data storage system like we have in stocky for symbols. SymbolMeta can contain many different types of data and be accessed in many different ways.


If the agent or setup.sh runs into file permissions accessing a particlar file. We should have a node meta data record that is a json blob which we update with the file name and the last time and process that experienced that error.

We should make this information available in the UI.