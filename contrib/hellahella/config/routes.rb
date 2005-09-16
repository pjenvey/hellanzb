ActionController::Routing::Routes.draw do |map|
  
  map.connect 'queue/:url', :controller => 'hellanzb', :action => 'enqueue_bookmarklet'
  
  map.connect ':controller/:action/:id'
  
  map.connect '', :controller => 'hellanzb', :action => 'index'
end
